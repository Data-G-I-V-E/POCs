"""
Answer Synthesizer

Combines results from all agents (SQL, Policy, Vector, Agreements) into a
coherent, markdown-formatted response with source citations.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser

from .state import AgentState
from prompts.synthesizer_prompt import SYNTHESIZER_SYSTEM_PROMPT, SYNTHESIZER_HUMAN_TEMPLATE


class AnswerSynthesizer:
    """Synthesizes final answer from all agent results"""
    
    def __init__(self, llm):
        self.llm = llm
        self.synthesis_prompt = ChatPromptTemplate.from_messages([
            ("system", SYNTHESIZER_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="messages"),
            ("human", SYNTHESIZER_HUMAN_TEMPLATE)
        ])
    
    def execute(self, state: AgentState) -> AgentState:
        """Synthesize final answer"""
        
        # Prepare results for synthesis
        sql_summary = "NOT CHECKED — SQL agent was not invoked for this query."
        if state.get("sql_results"):
            if state["sql_results"].get("success"):
                sql_summary = str(state["sql_results"]["result"])
            elif state["sql_results"].get("error"):
                sql_summary = f"Query failed: {state['sql_results']['error']}"
        
        policy_summary = "NOT CHECKED — Policy agent was not invoked for this query."
        if state.get("policy_results") and state["policy_results"].get("success"):
            result = state["policy_results"]["result"]
            if isinstance(result, dict):
                if "can_export" in result:
                    policy_summary = f"Export Allowed: {result['can_export']}\n"
                    policy_summary += f"Issues: {result.get('issues', [])}\n"
                    policy_summary += f"Warnings: {result.get('warnings', [])}\n"
                    policy_summary += f"Requirements: {result.get('requirements', [])}"
                    # Include HS info details if available
                    hs_info = result.get('hs_info', {})
                    if hs_info.get('is_prohibited'):
                        p_info = hs_info.get('prohibited_info', {})
                        policy_summary += f"\nPROHIBITED: {p_info.get('description', 'N/A')} - {p_info.get('policy_condition', 'Export not allowed')}"
                    if hs_info.get('is_restricted'):
                        r_info = hs_info.get('restricted_info', {})
                        policy_summary += f"\nRESTRICTED: {r_info.get('description', 'N/A')} - {r_info.get('policy_condition', 'Special conditions apply')}"
                    if hs_info.get('is_ste'):
                        s_info = hs_info.get('ste_info', {})
                        policy_summary += f"\nSTE REQUIRED: Export only via {s_info.get('authorized_entity', 'designated entity')}"
                else:
                    policy_summary = f"Description: {result.get('description', 'N/A')}\n"
                    policy_summary += f"Status: Prohibited={result.get('is_prohibited')}, Restricted={result.get('is_restricted')}, STE={result.get('is_ste')}"
                    if result.get('is_prohibited'):
                        p_info = result.get('prohibited_info', {})
                        policy_summary += f"\nPROHIBITED DETAILS: {p_info.get('description', 'N/A')} - {p_info.get('policy_condition', 'Export not allowed')}"
                    if result.get('is_restricted'):
                        r_info = result.get('restricted_info', {})
                        policy_summary += f"\nRESTRICTED DETAILS: {r_info.get('description', 'N/A')} - {r_info.get('policy_condition', 'Special conditions apply')}"
                    if result.get('is_ste'):
                        s_info = result.get('ste_info', {})
                        policy_summary += f"\nSTE DETAILS: Export only via {s_info.get('authorized_entity', 'designated entity')}"
        
        vector_summary = "NOT CHECKED — Vector agent was not invoked for this query."
        if state.get("vector_results"):
            docs = state["vector_results"][:2]
            vector_summary = "\n\n".join([
                f"Document: {d['metadata'].get('filename', 'N/A')}\nRelevance: {d['score']:.1%}\nExcerpt: {d['text'][:200]}..."
                for d in docs
            ])
        
        # Build agreement summary
        agreement_summary = "NOT CHECKED — Agreements agent was not invoked for this query."
        if state.get("agreement_results"):
            agreement_docs = state["agreement_results"]
            parts = []
            for d in agreement_docs[:4]:  # Top 4 agreement results
                article = d.get('article', 'N/A')
                agreement = d.get('agreement', 'N/A')
                country = d.get('country', 'N/A')
                doc_type = d.get('doc_type', '')
                score = d.get('score', 0)
                cross_refs = d.get('cross_ref_articles', '')
                is_xref = d.get('is_cross_ref', False)
                text_preview = d['text'][:300]
                
                entry = f"Agreement: {agreement}\n"
                entry += f"Country: {country.upper()}\n"
                if article:
                    entry += f"Article: {article}\n"
                if doc_type:
                    entry += f"Type: {doc_type}\n"
                entry += f"Relevance: {score:.1%}\n"
                if cross_refs:
                    entry += f"Cross-references: Articles {cross_refs}\n"
                if is_xref:
                    entry += "[Auto-resolved cross-reference]\n"
                entry += f"Content: {text_preview}..."
                parts.append(entry)
            
            agreement_summary = "\n\n---\n\n".join(parts)
        
        # Generate synthesis
        response = self.synthesis_prompt | self.llm | StrOutputParser()
        final_answer = response.invoke({
            "messages": state["messages"],
            "query": state["user_query"],
            "query_type": state.get("query_type", "unknown"),
            "sql_results": sql_summary,
            "policy_results": policy_summary,
            "vector_results": vector_summary,
            "agreement_results": agreement_summary
        })
        
        state["final_answer"] = final_answer
        state["next_agent"] = None
        
        return state
