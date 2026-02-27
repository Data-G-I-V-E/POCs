"""
Vector Agent

Searches DGFT policy documents and trade agreements using vector search.
Now searches both the agreements store AND the DGFT FTP policy store.
"""

import re
from datetime import datetime

from config import Config
from export_data_integrator import ExportDataIntegrator
from .state import AgentState


class VectorAgent:
    """Agent for searching agreements and DGFT FTP policies using vector search"""
    
    def __init__(self):
        self.integrator = ExportDataIntegrator(use_vector_stores=True)
        
        # Load DGFT FTP retriever
        self.dgft_retriever = None
        try:
            import sys as _sys
            _sys.path.insert(0, str(Config.ROOT_DIR / "storage-scripts"))
            from dgft_ftp_retriever import DGFTFTPRetriever
            
            dgft_path = Config.ROOT_DIR / "dgft_ftp_rag_store"
            if dgft_path.exists():
                self.dgft_retriever = DGFTFTPRetriever(storage_path=dgft_path)
                print("✓ VectorAgent: DGFT FTP retriever loaded")
            else:
                print("⚠️  VectorAgent: dgft_ftp_rag_store not found (run dgft_ftp_ingest.py)")
        except Exception as e:
            print(f"⚠️  VectorAgent: Could not load DGFT FTP retriever: {e}")
    
    def execute(self, state: AgentState) -> AgentState:
        """Search vector stores (agreements + DGFT FTP)"""
        try:
            results = []
            query = state["user_query"]
            
            # --- DGFT FTP search ---
            if self.dgft_retriever:
                # Check for direct section reference (e.g. "7.02", "section 4.01")
                section_match = re.search(
                    r'(?:section\s+)?(\d+\.\d{2,})',
                    query, re.IGNORECASE
                )
                
                dgft_hits = []
                if section_match:
                    # Direct section lookup first
                    section_id = section_match.group(1)
                    dgft_hits = self.dgft_retriever.search_section(section_id)
                
                # Always supplement with vector search
                vector_hits = self.dgft_retriever.search(
                    query=query,
                    top_k=3,
                )
                
                # Deduplicate
                seen = set()
                for doc in dgft_hits:
                    key = doc["text"][:100]
                    seen.add(key)
                    results.append({
                        "type": "dgft_ftp",
                        "text": doc["text"],
                        "metadata": doc["metadata"],
                        "score": doc["similarity_score"]
                    })
                
                for doc in vector_hits:
                    key = doc["text"][:100]
                    if key not in seen:
                        seen.add(key)
                        results.append({
                            "type": "dgft_ftp",
                            "text": doc["text"],
                            "metadata": doc["metadata"],
                            "score": doc["similarity_score"]
                        })
            
            # --- Agreements search (existing) ---
            if self.integrator.agreements_retriever:
                agreement_results = self.integrator.search_trade_agreements(
                    query=query,
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
                dgft_count = sum(1 for r in results if r["type"] == "dgft_ftp")
                agreement_count = sum(1 for r in results if r["type"] == "agreement")
                stores_used = []
                if dgft_count > 0:
                    stores_used.append("dgft_ftp_rag_store")
                if agreement_count > 0:
                    stores_used.append("agreements_chromadb")
                
                state["sources"].append({
                    "type": "vector_search",
                    "stores": stores_used,
                    "dgft_ftp_results": dgft_count,
                    "agreement_results": agreement_count,
                    "num_results": len(results),
                    "query": query,
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
