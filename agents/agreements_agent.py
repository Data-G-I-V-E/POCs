"""
Agreements Agent

Searches trade agreement PDFs (India-Australia ECTA, India-UAE CEPA, India-UK CETA)
using FAISS/ChromaDB vector search with cross-reference resolution.
"""

import re
from datetime import datetime

from config import Config
from .state import AgentState


class AgreementsAgent:
    """Agent for searching trade agreements with cross-reference resolution.
    
    Searches the ingested trade agreement PDFs (India-Australia ECTA, India-UAE CEPA,
    India-UK CETA) using FAISS/ChromaDB vector search. Returns relevant articles,
    rules of origin, tariff provisions, customs procedures, etc.
    """
    
    def __init__(self):
        self.retriever = None
        try:
            import sys as _sys
            _sys.path.insert(0, str(Config.ROOT_DIR / "storage-scripts"))
            from agreements_retriever import AgreementsRetriever
            
            agreements_path = Config.ROOT_DIR / "agreements_rag_store"
            if agreements_path.exists():
                self.retriever = AgreementsRetriever(storage_path=agreements_path)
                print("✓ AgreementsAgent: Retriever loaded")
            else:
                print("⚠️  AgreementsAgent: agreements_rag_store not found")
        except Exception as e:
            print(f"⚠️  AgreementsAgent: Could not load retriever: {e}")
    
    def execute(self, state: AgentState) -> AgentState:
        """Search trade agreements for relevant provisions"""
        query = state["user_query"]
        country = state.get("country")
        hs_code = state.get("hs_code")
        
        if not self.retriever:
            state["agreement_results"] = []
            state["sources"].append({
                "type": "agreements_error",
                "error": "Agreements retriever not available"
            })
            state["next_agent"] = "synthesizer"
            return state
        
        try:
            results = []
            seen_texts = set()  # Track seen text to avoid duplicates
            
            # --- Direct article lookup ---
            # Detect "Article X.Y" pattern in the query for precise retrieval
            article_match = re.search(
                r'article\s+(\d+(?:\.\d+)?)',
                query, re.IGNORECASE
            )
            
            if article_match and country:
                article_id = article_match.group(1)
                direct_hits = self.retriever.search_article(article_id, country)
                for doc in direct_hits:
                    meta = doc.get("metadata", {})
                    text = doc["text"]
                    seen_texts.add(text[:100])  # Track by first 100 chars
                    result_entry = {
                        "type": "trade_agreement",
                        "text": text,
                        "metadata": meta,
                        "score": doc["similarity_score"],
                        "source_type": "article_lookup",
                        "country": meta.get("country", country),
                        "agreement": meta.get("agreement", ""),
                        "article": meta.get("article_full", ""),
                        "doc_type": meta.get("doc_type", ""),
                        "cross_ref_articles": meta.get("cross_ref_articles", ""),
                        "cross_ref_annexes": meta.get("cross_ref_annexes", ""),
                        "is_cross_ref": False,
                    }
                    results.append(result_entry)
            
            # --- Vector similarity search (supplement) ---
            # Build an enriched search query for better retrieval
            search_query = query
            if hs_code:
                search_query = f"HS code {hs_code} {query}"
            
            # Primary search with cross-reference resolution
            agreement_hits = self.retriever.search(
                query=search_query,
                top_k=5,
                country=country,
                include_cross_refs=True
            )
            
            for doc in agreement_hits:
                text = doc["text"]
                # Skip if already found via direct article lookup
                if text[:100] in seen_texts:
                    continue
                seen_texts.add(text[:100])
                
                meta = doc.get("metadata", {})
                result_entry = {
                    "type": "trade_agreement",
                    "text": text,
                    "metadata": meta,
                    "score": doc["similarity_score"],
                    "source_type": doc.get("source", "unknown"),
                    "country": meta.get("country", "unknown"),
                    "agreement": meta.get("agreement", ""),
                    "article": meta.get("article_full", ""),
                    "doc_type": meta.get("doc_type", ""),
                    "cross_ref_articles": meta.get("cross_ref_articles", ""),
                    "cross_ref_annexes": meta.get("cross_ref_annexes", ""),
                    "is_cross_ref": doc.get("source") == "cross_reference",
                }
                results.append(result_entry)
            
            state["agreement_results"] = results
            
            # Add source attribution
            if results:
                countries_found = list(set(r["country"] for r in results))
                agreements_found = list(set(r["agreement"] for r in results if r["agreement"]))
                state["sources"].append({
                    "type": "trade_agreements",
                    "store": "agreements_rag_store (FAISS + ChromaDB)",
                    "num_results": len(results),
                    "countries": countries_found,
                    "agreements": agreements_found,
                    "cross_refs_included": sum(1 for r in results if r["is_cross_ref"]),
                    "query": search_query,
                    "timestamp": datetime.now().isoformat()
                })
            
        except Exception as e:
            state["agreement_results"] = []
            state["sources"].append({
                "type": "agreements_error",
                "error": str(e)
            })
        
        state["next_agent"] = "synthesizer"
        return state
