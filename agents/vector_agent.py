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
        
        # Load DGFT FTP retriever — Qdrant backend (with FAISS fallback)
        self.dgft_retriever = None
        try:
            import sys as _sys
            _sys.path.insert(0, str(Config.ROOT_DIR / "storage-scripts"))

            # ── Try Qdrant backend first ──────────────────────────────────
            try:
                from dgft_ftp_retriever_qdrant import DGFTFTPRetriever
                self.dgft_retriever = DGFTFTPRetriever()
                print("✓ VectorAgent: DGFT FTP retriever loaded (Qdrant backend)")
            except Exception as qdrant_err:
                print(f"⚠️  VectorAgent: Qdrant DGFT retriever failed ({qdrant_err}), trying FAISS…")

                # ── FAISS/ChromaDB fallback ───────────────────────────────
                from dgft_ftp_retriever import DGFTFTPRetriever as DGFTFTPRetrieverFAISS
                dgft_path = Config.ROOT_DIR / "dgft_ftp_rag_store"
                if dgft_path.exists():
                    self.dgft_retriever = DGFTFTPRetrieverFAISS(storage_path=dgft_path)
                    print("✓ VectorAgent: DGFT FTP retriever loaded (FAISS fallback)")
                else:
                    print("⚠️  VectorAgent: dgft_ftp_rag_store not found; run dgft_ftp_ingest_qdrant.py")
        except Exception as e:
            print(f"⚠️  VectorAgent: Could not load DGFT FTP retriever: {e}")
    
    # Query patterns that ask for chapter enumeration
    _CHAPTER_LIST_PATTERN = re.compile(
        r'\b(all\s+chapters?|list\s+chapters?|how\s+many\s+chapters?|chapters?\s+in\s+|'
        r'what\s+chapters?|chapter\s+list|chapters?\s+covered|chapters?\s+available)\b',
        re.IGNORECASE,
    )
    # Query patterns that reference a specific chapter number
    _CHAPTER_NUM_PATTERN = re.compile(
        r'\bchapter\s+(\d{1,2})\b',
        re.IGNORECASE,
    )

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

                # Check for chapter-listing intent
                is_chapter_list_query = bool(self._CHAPTER_LIST_PATTERN.search(query))

                # Check for specific chapter reference (e.g. "chapter 4", "explain chapter 7")
                chapter_num_match = self._CHAPTER_NUM_PATTERN.search(query)
                target_chapter_num = int(chapter_num_match.group(1)) if chapter_num_match else None

                dgft_hits = []
                if section_match:
                    # Direct section lookup first
                    section_id = section_match.group(1)
                    dgft_hits = self.dgft_retriever.search_section(section_id)

                if is_chapter_list_query:
                    # Inject stats so the synthesizer can enumerate all chapters
                    try:
                        stats = self.dgft_retriever.get_stats()
                        chapters = stats.get("chapters", [])
                        stats_text = (
                            f"DGFT Foreign Trade Policy contains {len(chapters)} chapters: "
                            + ", ".join(f"Chapter {c}" for c in sorted(int(c) for c in chapters))
                            + f". Total chunks indexed: {stats['total_chunks']}. "
                            f"Total sections: {stats['num_sections']}."
                        )
                        dgft_hits.insert(0, {
                            "text": stats_text,
                            "metadata": {"source": "DGFT_FTP", "section_id": "stats_summary",
                                         "section_full": "DGFT FTP Chapter Index"},
                            "similarity_score": 1.0,
                            "source": "stats",
                        })
                    except Exception as stats_err:
                        print(f"⚠️  Could not fetch DGFT stats: {stats_err}")

                # Determine top_k and chapter filter for vector search
                if is_chapter_list_query:
                    top_k = 6
                    chapter_filter = None
                elif target_chapter_num is not None:
                    top_k = 8   # fetch more chunks so the full chapter is covered
                    chapter_filter = target_chapter_num
                else:
                    top_k = 3
                    chapter_filter = None

                # Always supplement with vector search
                vector_hits = self.dgft_retriever.search(
                    query=query,
                    top_k=top_k,
                    chapter_num=chapter_filter,
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
