"""
Vector Agent

Searches DGFT policy documents and agreements using vector search (ChromaDB).
"""

from datetime import datetime

from export_data_integrator import ExportDataIntegrator
from .state import AgentState


class VectorAgent:
    """Agent for searching agreements and policies using vector search"""
    
    def __init__(self):
        self.integrator = ExportDataIntegrator(use_vector_stores=True)
    
    def execute(self, state: AgentState) -> AgentState:
        """Search vector stores"""
        try:
            results = []
            
            # Search agreements
            if self.integrator.agreements_retriever:
                agreement_results = self.integrator.search_trade_agreements(
                    query=state["user_query"],
                    country=state.get("country"),
                    top_k=3
                )
                
                for doc in agreement_results:
                    results.append({
                        "type": "agreement",
                        "text": doc["text"],
                        "metadata": doc["metadata"],
                        "score": doc["similarity_score"]
                    })
            
            state["vector_results"] = results
            
            # Add sources
            if results:
                state["sources"].append({
                    "type": "vector_search",
                    "store": "agreements_chromadb",
                    "num_results": len(results),
                    "query": state["user_query"],
                    "timestamp": datetime.now().isoformat()
                })
            
        except Exception as e:
            state["vector_results"] = []
            state["sources"].append({
                "type": "vector_search_error",
                "error": str(e)
            })
        
        state["next_agent"] = "synthesizer"
        return state
