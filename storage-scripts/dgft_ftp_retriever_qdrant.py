"""
DGFT FTP Retrieval Module — Qdrant + FastEmbed Backend

Uses FastEmbed (ONNX-based) instead of sentence-transformers/PyTorch.
No torch requirement on the deployment server.

Usage:
    retriever = DGFTFTPRetriever()
    results   = retriever.search("advance authorization scheme")
    chunks    = retriever.search_section("7.02")
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

_FASTEMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class DGFTFTPRetriever:
    """DGFT Foreign Trade Policy retrieval — Qdrant + FastEmbed backend."""

    def __init__(
        self,
        storage_path: Optional[Path] = None,
        model=None,   # kept for signature compatibility, unused
    ):
        if storage_path is None:
            storage_path = Config.ROOT_DIR / "dgft_ftp_rag_store"
        self.storage_path = Path(storage_path)

        if not self.storage_path.exists():
            raise FileNotFoundError(
                f"dgft_ftp_rag_store not found at {self.storage_path}\n"
                "Run dgft_ftp_ingest_qdrant.py first."
            )

        # ── FastEmbed model ────────────────────────────────────────────────
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
        self.collection = Config.QDRANT_DGFT_COLLECTION
        print(f"  ✓ DGFTFTPRetriever [Qdrant+FastEmbed]: '{self.collection}'")

        # ── documents.json ────────────────────────────────────────────────
        docs_path = self.storage_path / "documents.json"
        if docs_path.exists():
            with open(docs_path, "r", encoding="utf-8") as f:
                self.documents: List[Dict] = json.load(f)
            print(f"  ✓ DGFT FTP documents: {len(self.documents)}")
        else:
            self.documents = []

        # ── section_index.json ────────────────────────────────────────────
        section_path = self.storage_path / "section_index.json"
        if section_path.exists():
            with open(section_path, "r", encoding="utf-8") as f:
                self.section_index: Dict[str, List[Dict]] = json.load(f)
            print(f"  ✓ DGFT FTP section index: {len(self.section_index)} sections")
        else:
            self.section_index = {}

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 5,
        chapter_num: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        embedding = self._embed(query)

        qdrant_filter = None
        if chapter_num is not None:
            qdrant_filter = Filter(
                must=[FieldCondition(
                    key="chapter_num",
                    match=MatchValue(value=str(chapter_num)),
                )]
            )

        hits = self.client.query_points(
            collection_name=self.collection,
            query=embedding,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        ).points

        results = []
        for hit in hits:
            payload = hit.payload or {}
            results.append({
                "text":             payload.get("text", ""),
                "metadata":         {k: v for k, v in payload.items() if k != "text"},
                "similarity_score": float(hit.score),
                "source":           "qdrant",
            })
        return results

    def search_section(self, section_id: str) -> List[Dict[str, Any]]:
        """
        Direct O(1) lookup via section_index.json — no embedding needed.
        """
        if section_id not in self.section_index:
            return []

        results = []
        for entry in self.section_index[section_id]:
            vec_idx = entry["vector_index"]

            try:
                points = self.client.retrieve(
                    collection_name=self.collection,
                    ids=[vec_idx],
                    with_payload=True,
                )
                if points:
                    p = points[0]
                    payload = p.payload or {}
                    results.append({
                        "text":             payload.get("text", ""),
                        "metadata":         {k: v for k, v in payload.items()
                                             if k != "text"},
                        "similarity_score": 1.0,
                        "source":           "section_lookup",
                    })
                    continue
            except Exception:
                pass

            if vec_idx < len(self.documents):
                doc = self.documents[vec_idx]
                results.append({
                    "text":             doc["text"],
                    "metadata":         doc["metadata"],
                    "similarity_score": 1.0,
                    "source":           "section_lookup",
                })
        return results

    def get_stats(self) -> Dict[str, Any]:
        chapters: set = set()
        sections: set = set()
        for doc in self.documents:
            meta = doc.get("metadata", {})
            if meta.get("chapter_num"):
                chapters.add(meta["chapter_num"])
            if meta.get("section_id") and meta["section_id"] != "preamble":
                sections.add(meta["section_id"])
        try:
            info = self.client.get_collection(self.collection)
            total_vectors = (getattr(info, "points_count", None)
                             or getattr(info, "vectors_count", len(self.documents)))
        except Exception:
            total_vectors = len(self.documents)

        return {
            "total_chunks":       len(self.documents),
            "total_vectors":      total_vectors,
            "chapters":           sorted(chapters),
            "num_sections":       len(sections),
            "section_index_keys": len(self.section_index),
            "backend":            "qdrant+fastembed",
        }

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> List[float]:
        vec = list(self._embed_model.embed([text]))[0]
        vec = np.array(vec, dtype="float32")
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()


# ──────────────────────────────────────────────────────────────────────────
# Quick smoke-test
# ──────────────────────────────────────────────────────────────────────────

def demo():
    retriever = DGFTFTPRetriever()
    print("\n" + "=" * 60)
    print("DGFT FTP Retriever Demo (Qdrant + FastEmbed)")
    print("=" * 60)

    import json as _json
    print(f"\nStats: {_json.dumps(retriever.get_stats(), indent=2)}")

    for q in ["categories of supply", "advance authorization"]:
        print(f"\n{'─'*60}\nQuery: {q}")
        for i, r in enumerate(retriever.search(q, top_k=2), 1):
            meta = r["metadata"]
            print(f"  [{i}] {meta.get('section_full','N/A')} "
                  f"score={r['similarity_score']:.3f}")
            print(f"       {r['text'][:150]}...")

    print(f"\n{'─'*60}\nDirect section lookup: 7.02 (no embedding)")
    for h in retriever.search_section("7.02"):
        print(f"  {h['metadata'].get('section_full','N/A')}")
        print(f"  {h['text'][:200]}...")


if __name__ == "__main__":
    demo()
