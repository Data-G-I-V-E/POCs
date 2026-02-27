"""
DGFT FTP Retriever Module

Provides search capabilities over ingested DGFT Foreign Trade Policy chapters.
Supports both vector similarity search and direct section lookup.

Usage:
    from dgft_ftp_retriever import DGFTFTPRetriever
    retriever = DGFTFTPRetriever()
    results = retriever.search("categories of supply")
    results = retriever.search_section("7.02")
"""

import json
import faiss
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Optional
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings


class DGFTFTPRetriever:
    """Retrieval system for DGFT Foreign Trade Policy documents."""

    def __init__(self, storage_path: Optional[Path] = None,
                 model: Optional[SentenceTransformer] = None):
        """
        Initialize retriever with stored indexes.

        Args:
            storage_path: Path to the dgft_ftp_rag_store directory
            model: Optional pre-loaded SentenceTransformer
        """
        if storage_path is None:
            storage_path = Path(__file__).parent.parent / "dgft_ftp_rag_store"

        self.storage_path = Path(storage_path)

        if not self.storage_path.exists():
            raise FileNotFoundError(f"DGFT FTP store not found: {self.storage_path}")

        # Load embedding model
        if model:
            self.model = model
        else:
            self.model = SentenceTransformer('all-MiniLM-L6-v2')

        # Load FAISS index
        faiss_path = self.storage_path / "dgft_ftp.index"
        if faiss_path.exists():
            self.index = faiss.read_index(str(faiss_path))
            self.use_ip = True  # Inner product (normalized = cosine)
            print(f"  ✓ DGFT FTP FAISS index: {self.index.ntotal} vectors")
        else:
            raise FileNotFoundError(f"FAISS index not found: {faiss_path}")

        # Load documents
        docs_path = self.storage_path / "documents.json"
        if docs_path.exists():
            with open(docs_path, "r", encoding="utf-8") as f:
                self.documents = json.load(f)
            print(f"  ✓ DGFT FTP documents: {len(self.documents)}")
        else:
            self.documents = []

        # Load section index
        section_path = self.storage_path / "section_index.json"
        if section_path.exists():
            with open(section_path, "r", encoding="utf-8") as f:
                self.section_index = json.load(f)
            print(f"  ✓ DGFT FTP section index: {len(self.section_index)} sections")
        else:
            self.section_index = {}

        # Load ChromaDB
        chroma_path = self.storage_path / "dgft_ftp_chroma"
        self.collection = None
        if chroma_path.exists():
            try:
                client = chromadb.PersistentClient(
                    path=str(chroma_path),
                    settings=Settings(anonymized_telemetry=False)
                )
                self.collection = client.get_collection("dgft_ftp")
                print(f"  ✓ DGFT FTP ChromaDB: {self.collection.count()} docs")
            except Exception as e:
                print(f"  ⚠️  ChromaDB not available: {e}")

    def search(self, query: str, top_k: int = 5,
               chapter_num: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Search for relevant DGFT FTP chunks.

        Args:
            query: Natural language query
            top_k: Number of results
            chapter_num: Optional filter by chapter number

        Returns:
            List of relevant chunks with metadata and similarity scores
        """
        query_embedding = self.model.encode(query, convert_to_numpy=True).astype('float32')

        # Normalize for cosine similarity
        norm = np.linalg.norm(query_embedding)
        if norm > 0:
            query_embedding = query_embedding / norm

        # Use ChromaDB with filtering if available
        if self.collection is not None:
            return self._search_chroma(query_embedding, query, top_k, chapter_num)
        else:
            return self._search_faiss(query_embedding, top_k, chapter_num)

    def _search_chroma(self, query_embedding, query_text, top_k, chapter_num):
        """Search using ChromaDB with metadata filtering."""
        where_filter = None
        if chapter_num is not None:
            where_filter = {"chapter_num": str(chapter_num)}

        results = self.collection.query(
            query_embeddings=[query_embedding.tolist()],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        formatted = []
        for i in range(len(results["ids"][0])):
            distance = results["distances"][0][i]
            similarity = 1 / (1 + distance)

            formatted.append({
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "similarity_score": float(similarity),
                "source": "chromadb",
            })

        return formatted

    def _search_faiss(self, query_embedding, top_k, chapter_num):
        """Search using FAISS with optional post-filtering."""
        # Fetch extra results for filtering
        fetch_k = top_k * 3 if chapter_num else top_k
        query_vec = query_embedding.reshape(1, -1)
        scores, indices = self.index.search(query_vec, fetch_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.documents):
                continue
            
            doc = self.documents[idx]
            meta = doc["metadata"]

            # Filter by chapter if specified
            if chapter_num is not None and meta.get("chapter_num") != chapter_num:
                continue

            results.append({
                "text": doc["text"],
                "metadata": meta,
                "similarity_score": float(score),
                "source": "faiss",
            })

            if len(results) >= top_k:
                break

        return results

    def search_section(self, section_id: str) -> List[Dict[str, Any]]:
        """
        Directly fetch all chunks for a specific section.

        Args:
            section_id: Section number, e.g. "7.02"

        Returns:
            List of chunks belonging to that section
        """
        if section_id not in self.section_index:
            return []

        results = []
        for entry in self.section_index[section_id]:
            vec_idx = entry["vector_index"]
            if vec_idx < len(self.documents):
                doc = self.documents[vec_idx]
                results.append({
                    "text": doc["text"],
                    "metadata": doc["metadata"],
                    "similarity_score": 1.0,
                    "source": "section_lookup",
                })
        return results

    def get_stats(self) -> Dict:
        """Return summary statistics."""
        chapters = set()
        sections = set()
        for doc in self.documents:
            meta = doc.get("metadata", {})
            if meta.get("chapter_num"):
                chapters.add(meta["chapter_num"])
            if meta.get("section_id") and meta["section_id"] != "preamble":
                sections.add(meta["section_id"])

        return {
            "total_chunks": len(self.documents),
            "total_vectors": self.index.ntotal,
            "chapters": sorted(chapters),
            "num_sections": len(sections),
            "section_index_keys": len(self.section_index),
            "chromadb_available": self.collection is not None,
        }


# ── Demo ──────────────────────────────────────────────────────

def demo():
    """Quick demo of DGFT FTP retrieval."""
    retriever = DGFTFTPRetriever()
    
    print("\n" + "=" * 60)
    print("DGFT FTP Retriever Demo")
    print("=" * 60)
    
    stats = retriever.get_stats()
    print(f"\nStore stats: {json.dumps(stats, indent=2)}")
    
    queries = [
        "categories of supply",
        "deemed exports",
        "advance authorization",
        "export promotion capital goods",
    ]
    
    for q in queries:
        print(f"\n{'─' * 60}")
        print(f"Query: {q}")
        results = retriever.search(q, top_k=2)
        for i, r in enumerate(results):
            meta = r["metadata"]
            print(f"  [{i+1}] {meta.get('section_full', 'N/A')} "
                  f"(Ch-{meta.get('chapter_num')}, score={r['similarity_score']:.3f})")
            print(f"      {r['text'][:150]}...")
    
    # Direct section lookup
    print(f"\n{'─' * 60}")
    print("Direct section lookup: 7.02")
    hits = retriever.search_section("7.02")
    for h in hits:
        print(f"  {h['metadata'].get('section_full', 'N/A')}")
        print(f"  {h['text'][:200]}...")


if __name__ == "__main__":
    demo()
