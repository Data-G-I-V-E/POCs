"""
DGFT FTP Ingest Script — Qdrant Backend

Replaces dgft_ftp_ingest.py for the Qdrant deployment path.

Same strategy as agreements_ingest_qdrant.py:
  - Extracts vectors from dgft_ftp.index (FAISS) if it exists — no re-embed.
  - Falls back to re-embedding documents.json if FAISS is absent.
  - Qdrant point ID = integer vector_index → section_index.json unchanged.
  - chapter_num is stored as a string payload field for FieldCondition filtering.

Usage:
    python dgft_ftp_ingest_qdrant.py [--recreate]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import faiss
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config

BATCH_SIZE = 64    # keep batches small for cloud connections


def _connect_qdrant() -> QdrantClient:
    kwargs: Dict[str, Any] = {
        "url":     Config.QDRANT_URL,
        "timeout": 120,   # seconds — large payloads need more time on cloud
    }
    if Config.QDRANT_API_KEY:
        kwargs["api_key"] = Config.QDRANT_API_KEY
    return QdrantClient(**kwargs)


def _ensure_collection(client: QdrantClient, recreate: bool) -> None:
    collection = Config.QDRANT_DGFT_COLLECTION
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


def _load_vectors_from_faiss(faiss_path: Path) -> np.ndarray:
    print(f"  Loading FAISS index from {faiss_path}…")
    index = faiss.read_index(str(faiss_path))
    print(f"  FAISS ntotal={index.ntotal}, dim={index.d}")

    if hasattr(index, "reconstruct_n"):
        vectors = np.zeros((index.ntotal, index.d), dtype="float32")
        index.reconstruct_n(0, index.ntotal, vectors)
    else:
        vectors = faiss.vector_to_array(index.xb).reshape(index.ntotal, index.d)

    return vectors


def _embed_documents(documents: List[Dict]) -> np.ndarray:
    print("  No FAISS index found — re-embedding documents…")
    model = SentenceTransformer(Config.QDRANT_EMBEDDING_MODEL)
    texts = [doc["text"] for doc in documents]
    vecs = model.encode(
        texts, convert_to_numpy=True, batch_size=64, show_progress_bar=True
    ).astype("float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    return vecs / norms


def _upload_to_qdrant(
    client: QdrantClient,
    collection: str,
    documents: List[Dict],
    vectors: np.ndarray,
) -> None:
    total = len(documents)
    print(f"  Uploading {total} points to Qdrant in batches of {BATCH_SIZE}…")

    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        batch_docs = documents[start:end]
        batch_vecs = vectors[start:end]

        points = []
        for i, (doc, vec) in enumerate(zip(batch_docs, batch_vecs)):
            pid = start + i  # == vector_index

            payload: Dict[str, Any] = {"text": doc["text"]}
            meta = doc.get("metadata", {})
            payload.update(meta)

            # Ensure chapter_num is stored as a string for FieldCondition matching
            if "chapter_num" in payload:
                payload["chapter_num"] = str(payload["chapter_num"])

            points.append(
                PointStruct(id=pid, vector=vec.tolist(), payload=payload)
            )

        client.upsert(collection_name=collection, points=points, wait=True)

        if end % (BATCH_SIZE * 4) == 0 or end == total:
            print(f"  … {end}/{total} uploaded")

    print(f"  ✓ All {total} points uploaded to '{collection}'.")


def main(recreate: bool = False) -> None:
    storage_path = Config.ROOT_DIR / "dgft_ftp_rag_store"

    print("=" * 70)
    print("  DGFT FTP → QDRANT INGEST")
    print("=" * 70)

    # 1. Load documents.json
    docs_path = storage_path / "documents.json"
    if not docs_path.exists():
        print(f"❌  {docs_path} not found.")
        print("    Run dgft_ftp_ingest.py first to create documents.json.")
        sys.exit(1)

    print(f"\n[1] Loading documents from {docs_path}…")
    with open(docs_path, "r", encoding="utf-8") as f:
        documents: List[Dict] = json.load(f)
    print(f"    {len(documents)} chunks loaded.")

    # 2. Connect and prepare collection
    print("\n[2] Connecting to Qdrant…")
    client = _connect_qdrant()
    print(f"    Connected to {Config.QDRANT_URL}")
    _ensure_collection(client, recreate=recreate)

    # 3. Get vectors
    print("\n[3] Preparing vectors…")
    faiss_path = storage_path / "dgft_ftp.index"
    if faiss_path.exists():
        vectors = _load_vectors_from_faiss(faiss_path)
    else:
        vectors = _embed_documents(documents)

    if len(vectors) != len(documents):
        print(f"⚠️  Vector/document count mismatch. Re-embedding to fix…")
        vectors = _embed_documents(documents)

    # 4. Upload
    print("\n[4] Uploading to Qdrant…")
    _upload_to_qdrant(
        client,
        Config.QDRANT_DGFT_COLLECTION,
        documents,
        vectors,
    )

    # 5. Verification
    print("\n[5] Verifying…")
    info = client.get_collection(Config.QDRANT_DGFT_COLLECTION)
    count = getattr(info, 'points_count', None) or getattr(info, 'vectors_count', '?')
    print(f"    points_count = {count}")

    section_path = storage_path / "section_index.json"
    if section_path.exists():
        with open(section_path, "r", encoding="utf-8") as f:
            si = json.load(f)
        print(f"    section_index.json: {len(si)} sections (unchanged)")

    print("\n✅  Done! The DGFT FTP collection is ready in Qdrant.")
    print("    section_index.json and documents.json are unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload DGFT FTP docs to Qdrant")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate the Qdrant collection before uploading.",
    )
    args = parser.parse_args()
    main(recreate=args.recreate)
