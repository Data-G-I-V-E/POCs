"""
Export Advisory Graph — LangGraph Orchestrator

Wires all specialized agents together into a LangGraph workflow:
  Router → [SQL | Policy | Vector | Agreements | Combined] → Synthesizer

Manages session-based conversation memory and provides the main query() interface.
"""

import os
import re
from typing import Dict, List, Any, Optional
from datetime import datetime

import psycopg2
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from config import Config
from export_data_integrator import ExportDataIntegrator

from .state import AgentState
from .router import QueryRouter
from .sql_agent import SQLAgent
from .policy_agent import PolicyAgent
from .vector_agent import VectorAgent
from .agreements_agent import AgreementsAgent
from .synthesizer import AnswerSynthesizer


class ExportAdvisoryGraph:
    """Main LangGraph orchestrator"""
    
    def __init__(self, google_api_key: Optional[str] = None):
        """Initialize the graph"""
        
        # Setup LLM
        api_key = google_api_key or Config.GOOGLE_API_KEY or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("Google API key required. Set in .env or pass as parameter.")
        
        self.llm = ChatGoogleGenerativeAI(
            model=Config.LLM_MODEL,
            google_api_key=api_key,
            temperature=Config.LLM_TEMPERATURE
        )
        
        # Initialize agents
        self.router = QueryRouter(self.llm)
        self.sql_agent = SQLAgent(self.llm)
        self.policy_agent = PolicyAgent()
        self.vector_agent = VectorAgent()
        self.agreements_agent = AgreementsAgent()
        self.synthesizer = AnswerSynthesizer(self.llm)
        
        # Session-based conversation memory
        self.sessions: Dict[str, List[BaseMessage]] = {}
        
        # Build graph
        self.graph = self._build_graph()
    
    def _combined_execute(self, state: AgentState) -> AgentState:
        """Execute both SQL and Policy agents for complex queries"""
        # Run SQL agent first
        state = self.sql_agent.execute(state)
        
        # Run Policy agent (even without a specific HS code,
        # we do a chapter-level policy check)
        hs_code = state.get("hs_code")
        if hs_code:
            state = self.policy_agent.execute(state)
        else:
            # For chapter-level combined queries, do a batch policy check
            try:
                integrator = ExportDataIntegrator(use_vector_stores=False)
                query_lower = state["user_query"].lower()
                
                # Extract chapter numbers from query
                chapter_matches = re.findall(r'chapter\s*(\d{1,2})', query_lower)
                
                policy_data = {}
                conn = psycopg2.connect(**Config.DB_CONFIG)
                cursor = conn.cursor()
                
                for ch in chapter_matches:
                    ch_padded = ch.zfill(2)
                    
                    # Get prohibited items in this chapter
                    cursor.execute(
                        "SELECT hs_code, description, policy_condition FROM prohibited_items WHERE hs_code LIKE %s LIMIT 20",
                        (f"{ch_padded}%",)
                    )
                    prohibited = [{"hs_code": r[0], "description": r[1], "condition": r[2]} for r in cursor.fetchall()]
                    
                    # Get restricted items in this chapter
                    cursor.execute(
                        "SELECT hs_code, description, policy_condition FROM restricted_items WHERE hs_code LIKE %s LIMIT 20",
                        (f"{ch_padded}%",)
                    )
                    restricted = [{"hs_code": r[0], "description": r[1], "condition": r[2]} for r in cursor.fetchall()]
                    
                    # Get STE items in this chapter
                    cursor.execute(
                        "SELECT hs_code, description, authorized_entity, policy_condition FROM ste_items WHERE hs_code LIKE %s LIMIT 20",
                        (f"{ch_padded}%",)
                    )
                    ste = [{"hs_code": r[0], "description": r[1], "entity": r[2], "condition": r[3]} for r in cursor.fetchall()]
                    
                    # Get policy conditions for this chapter
                    cursor.execute(
                        "SELECT policy_type, policy_text FROM itc_chapter_policies WHERE chapter_code = %s ORDER BY policy_type",
                        (ch_padded,)
                    )
                    policies = [{"type": r[0], "text": r[1]} for r in cursor.fetchall()]
                    
                    policy_data[f"chapter_{ch_padded}"] = {
                        "prohibited": prohibited,
                        "restricted": restricted,
                        "ste": ste,
                        "policy_conditions": policies,
                        "prohibited_count": len(prohibited),
                        "restricted_count": len(restricted),
                        "ste_count": len(ste)
                    }
                
                cursor.close()
                conn.close()
                integrator.close()
                
                state["policy_results"] = {
                    "result": policy_data,
                    "success": True,
                    "chapters_checked": chapter_matches
                }
                
                state["sources"].append({
                    "type": "policy_check",
                    "chapters": chapter_matches,
                    "tables": ["prohibited_items", "restricted_items", "ste_items", "itc_chapter_policies"],
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                state["policy_results"] = {
                    "error": str(e),
                    "success": False
                }
        # Also search trade agreements if country is mentioned
        country = state.get("country")
        if country and self.agreements_agent.retriever:
            state = self.agreements_agent.execute(state)
        
        state["next_agent"] = "synthesizer"
        state["query_type"] = "combined"
        return state
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow"""
        
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("router", self.router.route)
        workflow.add_node("sql", self.sql_agent.execute)
        workflow.add_node("policy", self.policy_agent.execute)
        workflow.add_node("vector", self.vector_agent.execute)
        workflow.add_node("agreements", self.agreements_agent.execute)
        workflow.add_node("combined", self._combined_execute)
        workflow.add_node("synthesizer", self.synthesizer.execute)
        
        # Set entry point
        workflow.set_entry_point("router")
        
        # Add conditional edges from router
        workflow.add_conditional_edges(
            "router",
            lambda state: state["next_agent"],
            {
                "sql": "sql",
                "policy": "policy",
                "vector": "vector",
                "agreements": "agreements",
                "combined": "combined",
                "general": "synthesizer"
            }
        )
        
        # All agents go to synthesizer
        workflow.add_edge("sql", "synthesizer")
        workflow.add_edge("policy", "synthesizer")
        workflow.add_edge("vector", "synthesizer")
        workflow.add_edge("agreements", "synthesizer")
        workflow.add_edge("combined", "synthesizer")
        
        # Synthesizer is the end
        workflow.add_edge("synthesizer", END)
        
        return workflow.compile()
    
    def query(self, user_query: str, session_id: str = "default") -> Dict[str, Any]:
        """
        Process a user query through the multi-agent system with conversation memory
        
        Args:
            user_query: Natural language query
            session_id: Session identifier for maintaining conversation history
            
        Returns:
            Dict with answer and sources
        """
        
        # Initialize session if not exists
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        
        # Add user message to session history
        self.sessions[session_id].append(HumanMessage(content=user_query))
        
        # Initialize state with full conversation history
        initial_state = {
            "messages": list(self.sessions[session_id]),  # Copy full history
            "user_query": user_query,
            "query_type": None,
            "hs_code": None,
            "country": None,
            "sql_results": None,
            "vector_results": None,
            "policy_results": None,
            "agreement_results": None,
            "final_answer": None,
            "sources": [],
            "next_agent": None
        }
        
        # Run graph
        result = self.graph.invoke(initial_state)
        
        # Add assistant response to session history
        self.sessions[session_id].append(AIMessage(content=result["final_answer"]))
        
        # Format response
        return {
            "answer": result["final_answer"],
            "sources": result["sources"],
            "query_type": result["query_type"],
            "hs_code": result.get("hs_code"),
            "country": result.get("country"),
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }
    
    def clear_session(self, session_id: str = "default") -> None:
        """Clear conversation history for a session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def get_session_history(self, session_id: str = "default") -> List[Dict[str, str]]:
        """Get conversation history for a session"""
        if session_id not in self.sessions:
            return []
        
        history = []
        for msg in self.sessions[session_id]:
            if isinstance(msg, HumanMessage):
                history.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                history.append({"role": "assistant", "content": msg.content})
        return history
    
    def list_sessions(self) -> List[str]:
        """List all active session IDs"""
        return list(self.sessions.keys())
    
    def get_session_message_count(self, session_id: str = "default") -> int:
        """Get number of messages in a session"""
        return len(self.sessions.get(session_id, []))
    
    def format_response(self, result: Dict[str, Any]) -> str:
        """Format response for display"""
        
        output = []
        output.append("="*70)
        output.append("EXPORT ADVISORY RESPONSE")
        output.append("="*70)
        output.append(f"\n{result['answer']}\n")
        
        if result["sources"]:
            output.append("─"*70)
            output.append("SOURCES:")
            for i, source in enumerate(result["sources"], 1):
                output.append(f"\n{i}. Type: {source['type']}")
                if source['type'] == 'sql':
                    output.append(f"   Query: {source['query']}")
                    output.append(f"   Database: {source['database']}")
                elif source['type'] == 'policy_check':
                    output.append(f"   HS Code: {source['hs_code']}")
                    output.append(f"   Country: {source['country']}")
                    output.append(f"   Tables: {', '.join(source['tables'])}")
                elif source['type'] == 'vector_search':
                    output.append(f"   Store: {source['store']}")
                    output.append(f"   Results: {source['num_results']}")
                elif source['type'] == 'trade_agreements':
                    output.append(f"   Store: {source['store']}")
                    output.append(f"   Results: {source['num_results']}")
                    output.append(f"   Countries: {', '.join(source.get('countries', []))}")
                    output.append(f"   Agreements: {', '.join(source.get('agreements', []))}")
                    if source.get('cross_refs_included'):
                        output.append(f"   Cross-refs resolved: {source['cross_refs_included']}")
        
        output.append("\n" + "="*70)
        output.append(f"Query Type: {result['query_type']}")
        if result.get('hs_code'):
            output.append(f"HS Code: {result['hs_code']}")
        if result.get('country'):
            output.append(f"Country: {result['country']}")
        output.append(f"Timestamp: {result['timestamp']}")
        output.append("="*70)
        
        return "\n".join(output)


# ========== DEMO ==========

def interactive_demo():
    """Interactive demo of the multi-agent system"""
    
    print("="*70)
    print("LANGGRAPH MULTI-AGENT EXPORT ADVISORY SYSTEM")
    print("="*70)
    print("\nInitializing agents...")
    
    try:
        graph = ExportAdvisoryGraph()
        print("✓ System ready!\n")
    except Exception as e:
        print(f"❌ Error initializing: {e}")
        print("\nMake sure you have:")
        print("1. GOOGLE_API_KEY in .env file")
        print("2. Database connection working")
        print("3. Vector stores available")
        return
    
    # Example queries
    demo_queries = [
        "What is the total export value for chapter 07 to Australia?",
        "Can I export HS 070310 to Australia?",
        "What are the tariff requirements for exporting to UAE?",
        "Show me export statistics for HS 610910",
    ]
    
    print("Demo Queries:")
    for i, q in enumerate(demo_queries, 1):
        print(f"{i}. {q}")
    
    print("\n" + "="*70)
    
    # Run demo
    for query in demo_queries[:2]:  # Run first 2 for demo
        print(f"\n{'═'*70}")
        print(f"Query: {query}")
        print(f"{'═'*70}\n")
        
        try:
            result = graph.query(query)
            print(graph.format_response(result))
        except Exception as e:
            print(f"❌ Error: {e}")
        
        input("\nPress Enter for next query...")
    
    # Interactive mode
    print("\n" + "="*70)
    print("INTERACTIVE MODE - Ask your questions!")
    print("(Type 'quit' to exit)")
    print("="*70 + "\n")
    
    while True:
        user_input = input("\nYour query: ").strip()
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("\nGoodbye!")
            break
        
        if not user_input:
            continue
        
        try:
            result = graph.query(user_input)
            print("\n" + graph.format_response(result))
        except Exception as e:
            print(f"\n❌ Error: {e}")
