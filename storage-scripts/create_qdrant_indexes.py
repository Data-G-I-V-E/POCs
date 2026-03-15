"""
One-off script to create payload indexes on existing Qdrant collections.

Run this ONCE against your Qdrant cluster to enable filtered search.
You do NOT need to re-upload any vectors.

Usage:
    python storage-scripts/create_qdrant_indexes.py
"""

import sys
from pathlib import Path
from typing import Any, Dict

from qdrant_client import QdrantClient
from qdrant_client.models import PayloadSchemaType

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config


def _connect() -> QdrantClient:
    kwargs: Dict[str, Any] = {"url": Config.QDRANT_URL, "timeout": 60}
    if Config.QDRANT_API_KEY:
        kwargs["api_key"] = Config.QDRANT_API_KEY
    return QdrantClient(**kwargs)


def create_indexes(client: QdrantClient) -> None:
    # ── trade_agreements indexes ──────────────────────────────────────────
    print(f"Creating indexes on '{Config.QDRANT_AGREEMENTS_COLLECTION}'...")
    for field in ("country", "doc_type", "agreement"):
        client.create_payload_index(
            collection_name=Config.QDRANT_AGREEMENTS_COLLECTION,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )
        print(f"  ✓ {field} (keyword)")

    # ── dgft_ftp indexes ──────────────────────────────────────────────────
    print(f"\nCreating indexes on '{Config.QDRANT_DGFT_COLLECTION}'...")
    for field in ("chapter_num", "section_id"):
        client.create_payload_index(
            collection_name=Config.QDRANT_DGFT_COLLECTION,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )
        print(f"  ✓ {field} (keyword)")

    print("\n✅ Done — filtered search will now work correctly.")


if __name__ == "__main__":
    client = _connect()
    create_indexes(client)
