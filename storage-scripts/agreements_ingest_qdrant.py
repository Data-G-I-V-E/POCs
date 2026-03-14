"""
Trade Agreements Ingest Script — Qdrant Backend

Replaces agreements_ingest_enhanced.py.

Reads the same source data (trade agreement PDFs via agreements_ingest_enhanced
logic) but instead of writing to FAISS + ChromaDB, uploads vectors to Qdrant.

KEY CONSTRAINT: Qdrant point ID = integer position (vector_index) in the
documents list. This makes article_index.json, chunk_id_mapping.json, and
documents.json work unchanged with the new retriever.

Strategy for speed:
  - If agreements.index (FAISS) already exists, extract vectors directly
    from FAISS (no re-embedding needed). This is MUCH faster.
  - If no FAISS index exists, fall back to re-embedding from documents.json.
  - documents.json, article_index.json, chunk_id_mapping.json, and
    ingestion_stats.json are kept as-is (just copied/used, not regenerated).

Usage:
    python agreements_ingest_qdrant.py [--recreate]

Options:
    --recreate    Drop and recreate the Qdrant collection even if it exists.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import faiss
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

# Config from parent dir
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config

BATCH_SIZE = 64    # keep batches small for cloud connections (reduces payload per request)


def _connect_qdrant() -> QdrantClient:
    kwargs: Dict[str, Any] = {
        "url":     Config.QDRANT_URL,
        "timeout": 120,   # seconds — large payloads need more time on cloud
    }
    if Config.QDRANT_API_KEY:
        kwargs["api_key"] = Config.QDRANT_API_KEY
    return QdrantClient(**kwargs)


def _ensure_collection(client: QdrantClient, recreate: bool) -> None:
    """Create (or recreate) the Qdrant collection for agreements."""
    collection = Config.QDRANT_AGREEMENTS_COLLECTION
    dim = Config.QDRANT_EMBEDDING_DIM

    existing = [c.name for c in client.get_collections().collections]

    if collection in existing:
        if recreate:
            print(f"  Deleting existing collection '{collection}'…")
            client.delete_collection(collection)
        else:
            print(f"  Collection '{collection}' already exists (use --recreate to rebuild).")
            return

    print(f"  Creating collection '{collection}' (dim={dim}, cosine)…")
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
    )
    print(f"  ✓ Collection '{collection}' created.")


def _load_vectors_from_faiss(faiss_path: Path, n_docs: int) -> np.ndarray:
    """
    Extract raw (already-normalised) vectors from a FAISS FlatIP index.
    Returns shape (n, dim) float32 array.
    """
    print(f"  Loading FAISS index from {faiss_path}…")
    index = faiss.read_index(str(faiss_path))
    print(f"  FAISS ntotal={index.ntotal}")

    # Works for IndexFlatIP (and IDMap wrappers over FlatIP)
    if hasattr(index, "reconstruct_n"):
        vectors = np.zeros((index.ntotal, index.d), dtype="float32")
        index.reconstruct_n(0, index.ntotal, vectors)
    else:
        # Fallback: try IndexFlatIP's direct xb attribute
        vectors = faiss.vector_to_array(index.xb).reshape(index.ntotal, index.d)

    return vectors


def _embed_documents(documents: List[Dict]) -> np.ndarray:
    """Re-embed all documents (slow path — fallback when no FAISS index)."""
    print("  No FAISS index found — re-embedding documents (this may take a while)…")
    model = SentenceTransformer(Config.QDRANT_EMBEDDING_MODEL)
    texts = [doc["text"] for doc in documents]
    vecs = model.encode(texts, convert_to_numpy=True, batch_size=64,
                        show_progress_bar=True).astype("float32")                        

    # Normalise for cosine
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    return vecs / norms


def _upload_to_qdrant(
    client: QdrantClient,
    collection: str,
    documents: List[Dict],
    vectors: np.ndarray,
) -> None:
    """Batch-upload points to Qdrant. Point id == integer list position."""
    total = len(documents)
    print(f"  Uploading {total} points to Qdrant in batches of {BATCH_SIZE}…")

    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        batch_docs = documents[start:end]
        batch_vecs = vectors[start:end]

        points = []
        for i, (doc, vec) in enumerate(zip(batch_docs, batch_vecs)):
            pid = start + i  # == vector_index

            # Payload = metadata fields + text (flat dict for Qdrant filtering)
            payload: Dict[str, Any] = {"text": doc["text"]}
            payload.update(doc.get("metadata", {}))

            points.append(
                PointStruct(id=pid, vector=vec.tolist(), payload=payload)
            )

        client.upsert(collection_name=collection, points=points, wait=True)

        if end % (BATCH_SIZE * 4) == 0 or end == total:
            print(f"  … {end}/{total} uploaded")

    print(f"  ✓ All {total} points uploaded to '{collection}'.")


def main(recreate: bool = False) -> None:
    storage_path = Config.ROOT_DIR / "agreements_rag_store"

    print("=" * 70)
    print("  AGREEMENTS → QDRANT INGEST")
    print("=" * 70)

    # 1. Load documents.json (source of truth for text + metadata)
    docs_path = storage_path / "documents.json"
    if not docs_path.exists():
        print(f"❌  {docs_path} not found.")
        print("    Run agreements_ingest_enhanced.py first to create documents.json,")
        print("    or ensure the agreements_rag_store directory is populated.")
        sys.exit(1)

    print(f"\n[1] Loading documents from {docs_path}…")
    with open(docs_path, "r", encoding="utf-8") as f:
        documents: List[Dict] = json.load(f)
    print(f"    {len(documents)} chunks loaded.")

    # 2. Connect to Qdrant
    print("\n[2] Connecting to Qdrant…")
    client = _connect_qdrant()
    print(f"    Connected to {Config.QDRANT_URL}")
    _ensure_collection(client, recreate=recreate)

    # 3. Get vectors
    print("\n[3] Preparing vectors…")
    faiss_path = storage_path / "agreements.index"
    if faiss_path.exists():
        vectors = _load_vectors_from_faiss(faiss_path, len(documents))
    else:
        vectors = _embed_documents(documents)

    if len(vectors) != len(documents):
        print(f"⚠️  Vector count ({len(vectors)}) != document count ({len(documents)}). "
              "Will re-embed to ensure alignment.")
        vectors = _embed_documents(documents)

    # 4. Upload
    print("\n[4] Uploading to Qdrant…")
    _upload_to_qdrant(
        client,
        Config.QDRANT_AGREEMENTS_COLLECTION,
        documents,
        vectors,
    )

    # 5. Verification
    print("\n[5] Verifying…")
    info = client.get_collection(Config.QDRANT_AGREEMENTS_COLLECTION)
    count = getattr(info, 'points_count', None) or getattr(info, 'vectors_count', '?')
    print(f"    points_count = {count}")

    # Show stats from ingestion_stats.json if available
    stats_path = storage_path / "ingestion_stats.json"
    if stats_path.exists():
        with open(stats_path, "r", encoding="utf-8") as f:
            stats = json.load(f)
        print(f"    articles_parsed = {stats.get('articles_parsed', 'N/A')}")
        print(f"    cross_refs_found = {stats.get('cross_refs_found', 'N/A')}")

    print("\n✅  Done! The agreements collection is ready in Qdrant.")
    print(f"    article_index.json, documents.json, chunk_id_mapping.json untouched.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload trade agreements to Qdrant")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate the Qdrant collection before uploading.",
    )
    args = parser.parse_args()
    main(recreate=args.recreate)
