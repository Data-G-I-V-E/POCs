"""
Trade Agreements Retrieval Module — Qdrant + FastEmbed Backend

Uses FastEmbed (ONNX-based) instead of sentence-transformers/PyTorch.
No torch requirement on the deployment server.

FastEmbed runs the same all-MiniLM-L6-v2 model via ONNX (~80MB),
so embeddings are bit-for-bit compatible with the indexed vectors.

Usage:
    retriever = AgreementsRetriever()
    results   = retriever.search("Rules of origin for garlic to Australia",
                                 country="australia", include_cross_refs=True)
    chunks    = retriever.search_article("4.3", "australia")
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config

# FastEmbed model name matching the indexed vectors
_FASTEMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class AgreementsRetriever:
    """
    Retrieval system for trade agreements.
    Backend: Qdrant (vector store) + FastEmbed (ONNX embeddings, no torch).
    """

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        model=None,   # kept for signature compatibility, unused
    ):
        if storage_path is None:
            storage_path = Config.ROOT_DIR / "agreements_rag_store"
        self.storage_path = Path(storage_path)

        if not self.storage_path.exists():
            raise FileNotFoundError(
                f"agreements_rag_store not found at {self.storage_path}\n"
                "Run agreements_ingest_qdrant.py first."
            )

        # ── FastEmbed model (ONNX, torch-free) ───────────────────────────
        print(f"  Loading FastEmbed model: {_FASTEMBED_MODEL}")
        self._embed_model = TextEmbedding(_FASTEMBED_MODEL)

        # ── Qdrant client ─────────────────────────────────────────────────
        kwargs: Dict[str, Any] = {
            "url":     Config.QDRANT_URL,
            "timeout": 120,
        }
        if Config.QDRANT_API_KEY:
            kwargs["api_key"] = Config.QDRANT_API_KEY
        self.client = QdrantClient(**kwargs)
        self.collection = Config.QDRANT_AGREEMENTS_COLLECTION
        print(f"  ✓ AgreementsRetriever [Qdrant+FastEmbed]: '{self.collection}'")

        # ── documents.json ────────────────────────────────────────────────
        docs_path = self.storage_path / "documents.json"
        if docs_path.exists():
            with open(docs_path, "r", encoding="utf-8") as f:
                self.documents: List[Dict] = json.load(f)
            print(f"  ✓ documents.json: {len(self.documents)} chunks")
        else:
            raise FileNotFoundError(f"documents.json not found at {docs_path}")

        # ── article_index.json ────────────────────────────────────────────
        art_path = self.storage_path / "article_index.json"
        if art_path.exists():
            with open(art_path, "r", encoding="utf-8") as f:
                self.article_index: Dict[str, List[Dict]] = json.load(f)
            print(f"  ✓ article_index.json: {len(self.article_index)} articles")
        else:
            print("⚠️  article_index.json not found — cross-ref lookup unavailable")
            self.article_index = {}

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        country: Optional[str] = None,
        doc_type: Optional[str] = None,
        include_cross_refs: bool = False,
        use_chroma: bool = True,   # compatibility shim, ignored
    ) -> List[Dict[str, Any]]:
        embedding = self._embed(query)
        qdrant_filter = self._build_filter(country=country, doc_type=doc_type)

        hits = self.client.query_points(
            collection_name=self.collection,
            query=embedding,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        ).points

        results = [self._hit_to_result(h, source="qdrant") for h in hits]

        if include_cross_refs and results:
            results = self._resolve_cross_references(results, country)

        return results

    def search_by_country(
        self, query: str, country: str, top_k: int = 5,
        include_cross_refs: bool = False,
    ) -> List[Dict[str, Any]]:
        return self.search(query, top_k=top_k, country=country,
                           include_cross_refs=include_cross_refs)

    def search_article(self, article_id: str, country: str) -> List[Dict[str, Any]]:
        """
        Direct O(1) lookup via article_index.json — no embedding call needed.
        """
        key = f"{country.lower()}_{article_id}"
        if key not in self.article_index:
            return []

        results = []
        for entry in self.article_index[key]:
            vec_idx = entry["vector_index"]
            try:
                points = self.client.retrieve(
                    collection_name=self.collection,
                    ids=[vec_idx],
                    with_payload=True,
                )
                if points:
                    p = points[0]
                    results.append({
                        "text":             p.payload.get("text", ""),
                        "metadata":         {k: v for k, v in p.payload.items()
                                             if k != "text"},
                        "similarity_score": 1.0,
                        "source":           "article_lookup",
                    })
                    continue
            except Exception:
                pass

            # Fallback: documents.json
            if vec_idx < len(self.documents):
                doc = self.documents[vec_idx]
                results.append({
                    "text":             doc["text"],
                    "metadata":         doc["metadata"],
                    "similarity_score": 1.0,
                    "source":           "article_lookup",
                })
        return results

    def get_document_types(self, country: Optional[str] = None) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for doc in self.documents:
            if country and doc["metadata"].get("country", "").lower() != country.lower():
                continue
            dt = doc["metadata"].get("doc_type", "unknown")
            counts[dt] = counts.get(dt, 0) + 1
        return dict(sorted(counts.items(), key=lambda x: -x[1]))

    def get_available_countries(self) -> List[str]:
        return sorted({doc["metadata"]["country"]
                       for doc in self.documents if "country" in doc["metadata"]})

    def get_stats(self) -> Dict[str, Any]:
        stats_path = self.storage_path / "ingestion_stats.json"
        if stats_path.exists():
            with open(stats_path, "r", encoding="utf-8") as f:
                return json.load(f)
        info = self.client.get_collection(self.collection)
        count = getattr(info, "points_count", None) or getattr(info, "vectors_count", "?")
        return {
            "total_chunks":   count,
            "total_articles": len(self.article_index),
            "countries":      self.get_available_countries(),
            "backend":        "qdrant+fastembed",
        }

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> List[float]:
        """Embed a single query string using FastEmbed (ONNX, no torch)."""
        vec = list(self._embed_model.embed([text]))[0]
        vec = np.array(vec, dtype="float32")
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    @staticmethod
    def _build_filter(country: Optional[str], doc_type: Optional[str]) -> Optional[Filter]:
        conditions = []
        if country:
            conditions.append(FieldCondition(key="country",
                                              match=MatchValue(value=country.lower())))
        if doc_type:
            conditions.append(FieldCondition(key="doc_type",
                                              match=MatchValue(value=doc_type.lower())))
        return Filter(must=conditions) if conditions else None

    @staticmethod
    def _hit_to_result(hit, source: str = "qdrant") -> Dict[str, Any]:
        payload = hit.payload or {}
        return {
            "text":             payload.get("text", ""),
            "metadata":         {k: v for k, v in payload.items() if k != "text"},
            "similarity_score": float(hit.score),
            "source":           source,
        }

    def _resolve_cross_references(
        self, results: List[Dict[str, Any]], country: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        referenced = set()
        already_have = set()

        for r in results:
            art_id = r.get("metadata", {}).get("article_id", "")
            if art_id:
                already_have.add(art_id)
            xrefs = r.get("metadata", {}).get("cross_ref_articles", "")
            if xrefs:
                for ref in xrefs.split(","):
                    ref = ref.strip()
                    if ref and ref not in already_have:
                        referenced.add(ref)

        referenced -= already_have
        if not referenced:
            return results

        countries_to_check = (
            [country] if country
            else list({r.get("metadata", {}).get("country", "") for r in results})
        )

        cross_ref_results = []
        for art_id in referenced:
            for ctry in countries_to_check:
                if not ctry:
                    continue
                key = f"{ctry}_{art_id}"
                entries = self.article_index.get(key, [])
                if not entries:
                    continue
                vec_idx = entries[0]["vector_index"]
                try:
                    points = self.client.retrieve(
                        collection_name=self.collection,
                        ids=[vec_idx],
                        with_payload=True,
                    )
                    if points:
                        p = points[0]
                        cross_ref_results.append({
                            "text":     p.payload.get("text", ""),
                            "metadata": {
                                **{k: v for k, v in p.payload.items() if k != "text"},
                                "_cross_ref_source": True,
                                "_referenced_by":    "auto-resolved",
                            },
                            "similarity_score": 0.0,
                            "source": "cross_reference",
                        })
                        continue
                except Exception:
                    pass
                if vec_idx < len(self.documents):
                    doc = self.documents[vec_idx]
                    cross_ref_results.append({
                        "text":     doc["text"],
                        "metadata": {**doc["metadata"],
                                     "_cross_ref_source": True,
                                     "_referenced_by":    "auto-resolved"},
                        "similarity_score": 0.0,
                        "source": "cross_reference",
                    })

        return results + cross_ref_results[:3]


# ──────────────────────────────────────────────────────────────────────────
# Quick smoke-test
# ──────────────────────────────────────────────────────────────────────────

def demo_queries():
    print("=" * 70)
    print("  TRADE AGREEMENTS RETRIEVAL DEMO (Qdrant + FastEmbed)")
    print("=" * 70)
    retriever = AgreementsRetriever()
    print(f"\nCountries: {', '.join(retriever.get_available_countries())}")

    for query, country, include_refs in [
        ("Rules of origin for goods exported to Australia", "australia", True),
        ("Tariff concessions for UAE trade",                "uae",       False),
    ]:
        print(f"\n{'─'*60}")
        print(f"Query: {query}  [country={country}]")
        for i, r in enumerate(retriever.search(query, top_k=2, country=country,
                                               include_cross_refs=include_refs), 1):
            print(f"  [{i}] {r['metadata'].get('article_full','N/A')} "
                  f"score={r['similarity_score']:.4f}")
            print(f"       {r['text'][:150]}...")

    # Direct article lookup (no embedding)
    print(f"\n{'─'*60}")
    print("Direct article lookup: Article 4.2 (Australia) — no embedding call")
    for i, c in enumerate(retriever.search_article("4.2", "australia"), 1):
        print(f"  Chunk {i}: {c['text'][:150]}...")


if __name__ == "__main__":
    demo_queries()
