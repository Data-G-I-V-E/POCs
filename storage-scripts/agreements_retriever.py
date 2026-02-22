"""
Trade Agreements Retrieval Module for Multi-Agent Systems

Provides retrieval capabilities for agents to query trade agreements,
policies, and export/import regulations.

Features:
- Dual search: ChromaDB (metadata filtering) + FAISS (fast vector search)
- Cross-reference resolution: auto-fetches referenced Articles/Annexes
- Country and document type filtering
- Article-level metadata for precise results

Usage:
    retriever = AgreementsRetriever()
    results = retriever.search("Can I export wheat to Australia?", country="australia")
    results = retriever.search("Rules of origin", country="uae", include_cross_refs=True)
"""

import json
import re
import faiss
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings


class AgreementsRetriever:
    """Retrieval system for trade agreements optimized for agent queries"""

    def __init__(self, storage_path: Optional[Path] = None, model: Optional[SentenceTransformer] = None):
        """
        Initialize retriever with stored indexes.

        Args:
            storage_path: Path to the agreements_rag_store directory
            model: Optional pre-loaded SentenceTransformer to avoid double-loading
        """
        if storage_path is None:
            storage_path = Path(__file__).parent.parent / "agreements_rag_store"

        self.storage_path = Path(storage_path)

        if not self.storage_path.exists():
            raise FileNotFoundError(
                f"Storage path not found: {self.storage_path}\n"
                f"Run agreements_ingest_enhanced.py first to create the index."
            )

        # Load embedding model (or reuse provided one)
        if model is not None:
            self.model = model
        else:
            print("Loading embedding model...")
            self.model = SentenceTransformer('all-MiniLM-L6-v2')

        # Load FAISS index
        faiss_path = self.storage_path / "agreements.index"
        if faiss_path.exists():
            print("Loading FAISS index...")
            self.faiss_index = faiss.read_index(str(faiss_path))
            # Check if index uses inner product (cosine sim with normalized vectors)
            self.use_ip = True  # New index uses FlatIP with normalized vectors
        else:
            raise FileNotFoundError(f"FAISS index not found at {faiss_path}")

        # Load documents
        docs_path = self.storage_path / "documents.json"
        if docs_path.exists():
            print("Loading documents...")
            with open(docs_path, "r", encoding="utf-8") as f:
                self.documents = json.load(f)
        else:
            raise FileNotFoundError(f"Documents not found at {docs_path}")

        # Load article cross-reference index
        article_index_path = self.storage_path / "article_index.json"
        if article_index_path.exists():
            with open(article_index_path, "r", encoding="utf-8") as f:
                self.article_index = json.load(f)
            print(f"Loaded article index: {len(self.article_index)} articles")
        else:
            print("⚠️  Article index not found (cross-ref resolution unavailable)")
            self.article_index = {}

        # Load ChromaDB
        chroma_path = self.storage_path / "agreements_chroma"
        if chroma_path.exists():
            print("Loading ChromaDB...")
            self.chroma_client = chromadb.PersistentClient(
                path=str(chroma_path),
                settings=Settings(anonymized_telemetry=False)
            )
            try:
                self.collection = self.chroma_client.get_collection("trade_agreements")
            except Exception:
                print("⚠️  ChromaDB collection 'trade_agreements' not found")
                self.collection = None
        else:
            print("⚠️  ChromaDB not found, using FAISS only")
            self.chroma_client = None
            self.collection = None

        print(f"✓ Retriever initialized: {len(self.documents)} chunks, "
              f"{len(self.article_index)} articles\n")

    # ──────────────────────────────────────────────────────────
    # Main Search
    # ──────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        country: Optional[str] = None,
        doc_type: Optional[str] = None,
        include_cross_refs: bool = False,
        use_chroma: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant document chunks.

        Args:
            query: Natural language query
            top_k: Number of results to return
            country: Filter by country (australia, uae, uk)
            doc_type: Filter by document type (agreement, annex, rules_of_origin, etc.)
            include_cross_refs: If True, also fetch chunks for cross-referenced Articles
            use_chroma: Use ChromaDB for filtering (falls back to FAISS if unavailable)

        Returns:
            List of relevant document chunks with metadata and similarity scores
        """
        # Generate query embedding
        query_embedding = self.model.encode(query, convert_to_numpy=True).astype('float32')

        # Normalize for cosine similarity (FlatIP index)
        if self.use_ip:
            norm = np.linalg.norm(query_embedding)
            if norm > 0:
                query_embedding = query_embedding / norm

        # Use ChromaDB with metadata filtering if available
        if use_chroma and self.collection is not None:
            results = self._search_chroma(query_embedding, query, top_k, country, doc_type)
        else:
            results = self._search_faiss(query_embedding, top_k, country, doc_type)

        # Optionally resolve cross-references
        if include_cross_refs and results:
            results = self._resolve_cross_references(results, country)

        return results

    # ──────────────────────────────────────────────────────────
    # ChromaDB Search (with metadata filtering)
    # ──────────────────────────────────────────────────────────

    def _search_chroma(
        self,
        query_embedding: np.ndarray,
        query_text: str,
        top_k: int,
        country: Optional[str],
        doc_type: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Search using ChromaDB with metadata filtering"""

        # Build proper ChromaDB where filter
        where_filter = None
        conditions = []
        if country:
            conditions.append({"country": country.lower()})
        if doc_type:
            conditions.append({"doc_type": doc_type.lower()})

        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        # Query ChromaDB
        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        # Format results
        formatted_results = []
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i]
            # ChromaDB returns L2 distance; convert to similarity score
            similarity = 1 / (1 + distance)

            formatted_results.append({
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "similarity_score": float(similarity),
                "source": "chromadb",
            })

        return formatted_results

    # ──────────────────────────────────────────────────────────
    # FAISS Search (with post-filtering)
    # ──────────────────────────────────────────────────────────

    def _search_faiss(
        self,
        query_embedding: np.ndarray,
        top_k: int,
        country: Optional[str],
        doc_type: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Search using FAISS with post-filtering"""

        # Get more results than needed to allow for filtering
        search_k = min(top_k * 10, len(self.documents))

        # FAISS search
        scores, indices = self.faiss_index.search(
            query_embedding.reshape(1, -1).astype('float32'),
            search_k,
        )

        # Post-filter and format results
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1 or idx >= len(self.documents):
                continue

            doc = self.documents[idx]
            metadata = doc["metadata"]

            # Apply filters
            if country and metadata.get("country", "").lower() != country.lower():
                continue
            if doc_type and metadata.get("doc_type", "").lower() != doc_type.lower():
                continue

            # For IP index, score IS the similarity (higher = better)
            similarity = float(score) if self.use_ip else 1 / (1 + float(score))

            results.append({
                "text": doc["text"],
                "metadata": metadata,
                "similarity_score": similarity,
                "source": "faiss",
            })

            if len(results) >= top_k:
                break

        return results

    # ──────────────────────────────────────────────────────────
    # Cross-Reference Resolution
    # ──────────────────────────────────────────────────────────

    def _resolve_cross_references(
        self,
        results: List[Dict[str, Any]],
        country: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Look at the cross-references in returned chunks and fetch
        the referenced Article chunks automatically.

        This handles the common pattern in trade agreements where
        Article 4.2 says "as provided for in Article 4.4" — we fetch
        Article 4.4 too.
        """
        # Collect all referenced article IDs from the results
        referenced_articles = set()
        result_article_ids = set()

        for r in results:
            meta = r.get("metadata", {})

            # Track which articles we already have
            art_id = meta.get("article_id", "")
            if art_id:
                result_article_ids.add(art_id)

            # Collect cross-referenced articles
            cross_refs = meta.get("cross_ref_articles", "")
            if cross_refs:
                for ref in cross_refs.split(","):
                    ref = ref.strip()
                    if ref and ref not in result_article_ids:
                        referenced_articles.add(ref)

        # Remove articles we already have in results
        referenced_articles -= result_article_ids

        if not referenced_articles:
            return results

        # Fetch referenced articles from the article index
        cross_ref_results = []
        countries_to_check = [country] if country else list(
            set(r.get("metadata", {}).get("country", "") for r in results)
        )

        for art_id in referenced_articles:
            for ctry in countries_to_check:
                if not ctry:
                    continue
                key = f"{ctry}_{art_id}"
                if key in self.article_index:
                    entries = self.article_index[key]
                    # Get the first chunk of this article (the main content)
                    if entries:
                        entry = entries[0]
                        vec_idx = entry["vector_index"]
                        if vec_idx < len(self.documents):
                            doc = self.documents[vec_idx]
                            cross_ref_results.append({
                                "text": doc["text"],
                                "metadata": {
                                    **doc["metadata"],
                                    "_cross_ref_source": True,
                                    "_referenced_by": "auto-resolved",
                                },
                                "similarity_score": 0.0,  # Not from search
                                "source": "cross_reference",
                            })

        # Append cross-ref results at the end (lower priority)
        # Limit how many cross-refs we add to avoid flooding
        max_cross_refs = 3
        return results + cross_ref_results[:max_cross_refs]

    # ──────────────────────────────────────────────────────────
    # Convenience Methods
    # ──────────────────────────────────────────────────────────

    def search_by_country(self, query: str, country: str, top_k: int = 5,
                          include_cross_refs: bool = False) -> List[Dict[str, Any]]:
        """Convenience method to search within a specific country's agreements"""
        return self.search(query, top_k=top_k, country=country,
                          include_cross_refs=include_cross_refs)

    def search_article(self, article_id: str, country: str) -> List[Dict[str, Any]]:
        """
        Directly fetch all chunks for a specific Article.

        Args:
            article_id: Article number, e.g. "4.3"
            country: Country name, e.g. "australia"

        Returns:
            List of chunks belonging to that article
        """
        key = f"{country.lower()}_{article_id}"
        if key not in self.article_index:
            return []

        results = []
        for entry in self.article_index[key]:
            vec_idx = entry["vector_index"]
            if vec_idx < len(self.documents):
                doc = self.documents[vec_idx]
                results.append({
                    "text": doc["text"],
                    "metadata": doc["metadata"],
                    "similarity_score": 1.0,
                    "source": "article_lookup",
                })
        return results

    def get_document_types(self, country: Optional[str] = None) -> Dict[str, int]:
        """Get count of document types, optionally filtered by country"""
        type_counts = {}
        for doc in self.documents:
            if country and doc["metadata"].get("country", "").lower() != country.lower():
                continue
            doc_type = doc["metadata"].get("doc_type", "unknown")
            type_counts[doc_type] = type_counts.get(doc_type, 0) + 1
        return dict(sorted(type_counts.items(), key=lambda x: -x[1]))

    def get_available_countries(self) -> List[str]:
        """Get list of available countries"""
        countries = set()
        for doc in self.documents:
            if "country" in doc["metadata"]:
                countries.add(doc["metadata"]["country"])
        return sorted(list(countries))

    def get_stats(self) -> Dict[str, Any]:
        """Return summary statistics about the stored agreements"""
        stats_path = self.storage_path / "ingestion_stats.json"
        if stats_path.exists():
            with open(stats_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "total_chunks": len(self.documents),
            "total_articles": len(self.article_index),
            "countries": self.get_available_countries(),
        }


# ──────────────────────────────────────────────────────────────
# Demo
# ──────────────────────────────────────────────────────────────

def demo_queries():
    """Demonstrate retrieval with common agent queries"""
    print("=" * 70)
    print("  TRADE AGREEMENTS RETRIEVAL DEMO")
    print("=" * 70)

    retriever = AgreementsRetriever()

    # Show available data
    print(f"\nAvailable Countries: {', '.join(retriever.get_available_countries())}")
    print(f"\nDocument Types:")
    for doc_type, count in retriever.get_document_types().items():
        print(f"  - {doc_type}: {count} chunks")

    # Example queries that agents might ask
    queries = [
        ("Rules of origin for goods exported to Australia", "australia", True),
        ("What are the tariff concessions for UAE trade?", "uae", True),
        ("SPS sanitary measures for UK exports", "uk", False),
        ("What items are restricted or prohibited?", None, False),
        ("Customs procedures and trade facilitation", None, False),
    ]

    for query, country, include_refs in queries:
        print(f"\n{'=' * 70}")
        print(f"  Query: {query}")
        if country:
            print(f"  Country Filter: {country.upper()}")
        print(f"  Include Cross-Refs: {include_refs}")
        print(f"{'=' * 70}")

        results = retriever.search(
            query, top_k=3, country=country, include_cross_refs=include_refs
        )

        for i, result in enumerate(results, 1):
            meta = result["metadata"]
            source = result["source"]
            score = result["similarity_score"]

            print(f"\n  --- Result {i} (Score: {score:.4f}, Source: {source}) ---")
            print(f"  Country:  {meta.get('country', 'N/A')}")
            print(f"  Document: {meta.get('filename', 'N/A')}")
            print(f"  Type:     {meta.get('doc_type', 'N/A')}")
            print(f"  Article:  {meta.get('article_full', 'N/A')}")

            # Show cross-references if present
            cross_arts = meta.get("cross_ref_articles", "")
            cross_annex = meta.get("cross_ref_annexes", "")
            if cross_arts:
                print(f"  Refs →    Articles: {cross_arts}")
            if cross_annex:
                print(f"  Refs →    Annexes: {cross_annex}")

            # Show text preview
            text_preview = result["text"][:250].replace("\n", " ")
            print(f"  Text:     {text_preview}...")

    # Demo: Direct article lookup
    print(f"\n{'=' * 70}")
    print(f"  DIRECT ARTICLE LOOKUP: Article 4.2 (Australia)")
    print(f"{'=' * 70}")

    article_chunks = retriever.search_article("4.2", "australia")
    for i, chunk in enumerate(article_chunks, 1):
        print(f"\n  Chunk {i}: {chunk['text'][:200]}...")


if __name__ == "__main__":
    demo_queries()
