"""
DGFT Foreign Trade Policy (FTP) Ingestion for RAG

Reads DGFT FTP chapter PDFs from data/policies/DGFT_FTP/,
chunks them by section (e.g. 7.02, 4.01), embeds with SentenceTransformer,
and stores in FAISS + ChromaDB for vector search.

Usage:
    python storage-scripts/dgft_ftp_ingest.py
"""

import json
import re
import hashlib
import fitz          # PyMuPDF
import faiss
import numpy as np
import chromadb
from pathlib import Path
from typing import List, Dict, Any
from sentence_transformers import SentenceTransformer
from chromadb.config import Settings

# ── Configuration ─────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data" / "policies" / "DGFT_FTP"
OUTPUT_DIR = ROOT_DIR / "dgft_ftp_rag_store"
FAISS_INDEX_PATH = OUTPUT_DIR / "dgft_ftp.index"
CHROMA_DB_PATH = OUTPUT_DIR / "dgft_ftp_chroma"

MAX_CHUNK_CHARS = 1200
MIN_CHUNK_CHARS = 80
OVERLAP_CHARS = 150

OUTPUT_DIR.mkdir(exist_ok=True)
CHROMA_DB_PATH.mkdir(exist_ok=True)

# Embedding model (same as agreements for consistency)
print("Loading embedding model...")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
EMBEDDING_DIM = 384

# ChromaDB
chroma_client = chromadb.PersistentClient(
    path=str(CHROMA_DB_PATH),
    settings=Settings(anonymized_telemetry=False)
)


# ── Text Extraction ──────────────────────────────────────────

def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from a DGFT FTP chapter PDF."""
    try:
        doc = fitz.open(str(pdf_path))
        pages = [page.get_text() for page in doc]
        doc.close()
        text = "\n\n".join(pages)
        # Basic cleanup
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()
    except Exception as e:
        print(f"  ⚠️  Failed to extract {pdf_path.name}: {e}")
        return ""


# ── Metadata Extraction ──────────────────────────────────────

def extract_chapter_metadata(pdf_path: Path) -> Dict:
    """Extract chapter number and name from filename like Ch-7.pdf."""
    filename = pdf_path.stem  # e.g. "Ch-7"
    chapter_match = re.search(r'Ch-(\d+)', filename, re.IGNORECASE)
    chapter_num = int(chapter_match.group(1)) if chapter_match else 0
    
    return {
        "source": "DGFT_FTP",
        "document_type": "foreign_trade_policy",
        "chapter_num": chapter_num,
        "chapter": f"Chapter {chapter_num}",
        "filename": pdf_path.name,
    }


# ── Section-Aware Chunking ───────────────────────────────────

def split_into_sections(text: str, chapter_num: int) -> List[Dict]:
    """
    Split DGFT FTP chapter text into section-level chunks.
    
    DGFT FTP uses numbering like:
      - 7.01, 7.02, 7.03 (major sections)
      - 4.01, 4.02 etc.
      - Sometimes (a), (b), (c) sub-items within
    """
    # Pattern: section numbers like "7.01" or "7.02" at start of line
    # Also handles formats like "7.01 " or "\n7.01 "
    section_pattern = re.compile(
        r'(?:^|\n)\s*(\d+\.\d{2,})\s+(.+?)(?=\n)',
        re.MULTILINE
    )
    
    matches = list(section_pattern.finditer(text))
    
    if not matches:
        # No sections found — return entire text as one chunk
        return [{
            "text": text.strip(),
            "section_id": None,
            "section_title": None,
            "section_full": None,
        }]
    
    sections = []
    
    for i, match in enumerate(matches):
        section_id = match.group(1)     # e.g. "7.02"
        section_title = match.group(2).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        
        section_text = text[start:end].strip()
        
        if len(section_text) < MIN_CHUNK_CHARS:
            continue
        
        sections.append({
            "text": section_text,
            "section_id": section_id,
            "section_title": section_title[:120],  # Cap title length
            "section_full": f"Section {section_id}: {section_title[:120]}",
        })
    
    # Capture preamble before first section
    if matches and matches[0].start() > MIN_CHUNK_CHARS:
        preamble = text[:matches[0].start()].strip()
        if len(preamble) >= MIN_CHUNK_CHARS:
            sections.insert(0, {
                "text": preamble,
                "section_id": "preamble",
                "section_title": "Introduction / Preamble",
                "section_full": f"Chapter {chapter_num} Preamble",
            })
    
    return sections


def sub_chunk_with_overlap(text: str, max_chars: int = MAX_CHUNK_CHARS,
                           overlap: int = OVERLAP_CHARS) -> List[str]:
    """Split long text into sub-chunks with overlap at paragraph/sentence boundaries."""
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + max_chars
        
        if end >= len(text):
            chunks.append(text[start:].strip())
            break
        
        chunk_text = text[start:end]
        
        # Prefer paragraph break
        last_para = chunk_text.rfind('\n\n')
        if last_para > max_chars * 0.4:
            end = start + last_para + 2
        else:
            last_period = chunk_text.rfind('. ')
            if last_period > max_chars * 0.4:
                end = start + last_period + 2
            else:
                last_semi = chunk_text.rfind('; ')
                if last_semi > max_chars * 0.4:
                    end = start + last_semi + 2
        
        chunks.append(text[start:end].strip())
        start = end - overlap
    
    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS]


def chunk_chapter(text: str, doc_metadata: Dict) -> List[Dict]:
    """
    Main chunking pipeline:
    1. Split into sections
    2. Sub-chunk large sections with overlap
    3. Attach metadata
    """
    chapter_num = doc_metadata["chapter_num"]
    sections = split_into_sections(text, chapter_num)
    all_chunks = []
    chunk_idx = 0
    
    for section in sections:
        section_text = section["text"]
        sub_chunks = sub_chunk_with_overlap(section_text)
        
        for sub_idx, chunk_text in enumerate(sub_chunks):
            chunk_data = {
                "text": chunk_text,
                "metadata": {
                    **doc_metadata,
                    "chunk_id": chunk_idx,
                    "section_id": section["section_id"],
                    "section_title": section["section_title"],
                    "section_full": section["section_full"],
                    "sub_chunk": sub_idx if len(sub_chunks) > 1 else 0,
                    "total_sub_chunks": len(sub_chunks),
                    "text_length": len(chunk_text),
                }
            }
            all_chunks.append(chunk_data)
            chunk_idx += 1
    
    return all_chunks


def generate_chunk_id(text: str, metadata: Dict) -> str:
    """Generate unique, deterministic ID for a chunk."""
    key = f"dgft_ftp_{metadata.get('chapter_num', 0)}_{metadata.get('section_id', 'x')}_{metadata.get('chunk_id', 0)}"
    return hashlib.md5(key.encode()).hexdigest()[:16]


# ── Main Ingestion ────────────────────────────────────────────

def ingest_dgft_ftp():
    """Main ingestion pipeline for DGFT FTP chapters."""
    print("=" * 70)
    print("  DGFT FOREIGN TRADE POLICY INGESTION")
    print("  Section-aware chunking | FAISS + ChromaDB")
    print("=" * 70)
    
    if not DATA_DIR.exists():
        print(f"❌ Data directory not found: {DATA_DIR}")
        return
    
    pdf_files = sorted(DATA_DIR.glob("Ch-*.pdf"))
    if not pdf_files:
        print(f"❌ No Ch-*.pdf files found in {DATA_DIR}")
        return
    
    print(f"Found {len(pdf_files)} chapter PDFs")
    
    # Storage
    all_embeddings = []
    all_documents = []
    
    # ChromaDB — recreate fresh
    try:
        chroma_client.delete_collection("dgft_ftp")
    except Exception:
        pass
    
    collection = chroma_client.create_collection(
        name="dgft_ftp",
        metadata={
            "description": "DGFT Foreign Trade Policy chapters",
            "features": "section-aware chunking",
        }
    )
    
    # Section index for direct lookup
    section_index = {}  # { "7.02": [{"vector_index": 5, ...}], ... }
    
    global_idx = 0
    total_chunks = 0
    total_sections = 0
    
    for pdf_idx, pdf_file in enumerate(pdf_files, 1):
        file_size_kb = pdf_file.stat().st_size / 1024
        print(f"\n  [{pdf_idx}/{len(pdf_files)}] {pdf_file.name} ({file_size_kb:.0f} KB)")
        
        # Extract metadata
        doc_metadata = extract_chapter_metadata(pdf_file)
        
        # Extract text
        full_text = extract_pdf_text(pdf_file)
        if not full_text or len(full_text) < MIN_CHUNK_CHARS:
            print(f"    ⚠️  No usable text, skipping")
            continue
        
        print(f"    Text length: {len(full_text):,} chars")
        
        # Chunk
        content_chunks = chunk_chapter(full_text, doc_metadata)
        if not content_chunks:
            print(f"    ⚠️  No chunks produced, skipping")
            continue
        
        section_ids = set()
        
        # Process chunks
        batch_ids = []
        batch_embeddings = []
        batch_documents = []
        batch_metadatas = []
        
        for chunk_data in content_chunks:
            chunk_text = chunk_data["text"]
            chunk_meta = chunk_data["metadata"]
            
            sid = chunk_meta.get("section_id")
            if sid and sid != "preamble":
                section_ids.add(sid)
            
            # Build section index entry
            if sid:
                key = str(sid)
                if key not in section_index:
                    section_index[key] = []
                section_index[key].append({
                    "vector_index": global_idx,
                    "chapter_num": chunk_meta["chapter_num"],
                    "section_full": chunk_meta.get("section_full", ""),
                })
            
            # Generate embedding
            embedding = embedding_model.encode(chunk_text, convert_to_numpy=True)
            
            # Generate ID
            chunk_id = generate_chunk_id(chunk_text, chunk_meta)
            
            # FAISS storage
            all_embeddings.append(embedding)
            all_documents.append({
                "id": chunk_id,
                "text": chunk_text,
                "metadata": chunk_meta,
                "vector_index": global_idx,
            })
            
            # ChromaDB batch
            chroma_meta = {}
            for k, v in chunk_meta.items():
                if v is None:
                    chroma_meta[k] = ""
                elif isinstance(v, bool):
                    chroma_meta[k] = str(v).lower()
                elif isinstance(v, (int, float)):
                    chroma_meta[k] = str(v)
                else:
                    chroma_meta[k] = str(v)
            
            batch_ids.append(chunk_id)
            batch_embeddings.append(embedding.tolist())
            batch_documents.append(chunk_text)
            batch_metadatas.append(chroma_meta)
            
            global_idx += 1
        
        # Add batch to ChromaDB
        if batch_ids:
            # ChromaDB has a batch size limit
            BATCH_SIZE = 100
            for i in range(0, len(batch_ids), BATCH_SIZE):
                end = min(i + BATCH_SIZE, len(batch_ids))
                collection.add(
                    ids=batch_ids[i:end],
                    embeddings=batch_embeddings[i:end],
                    documents=batch_documents[i:end],
                    metadatas=batch_metadatas[i:end],
                )
        
        total_chunks += len(content_chunks)
        total_sections += len(section_ids)
        print(f"    ✓ {len(content_chunks)} chunks, {len(section_ids)} sections")
    
    # ── Build FAISS Index ──
    print(f"\n{'=' * 70}")
    print("Building FAISS index...")
    
    if not all_embeddings:
        print("❌ No embeddings generated!")
        return
    
    embedding_matrix = np.array(all_embeddings).astype('float32')
    
    # Normalize for cosine similarity
    norms = np.linalg.norm(embedding_matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    embedding_matrix = embedding_matrix / norms
    
    # Create FlatIP index (cosine similarity via inner product on normalized vectors)
    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    index.add(embedding_matrix)
    
    faiss.write_index(index, str(FAISS_INDEX_PATH))
    print(f"✓ FAISS index saved: {FAISS_INDEX_PATH}")
    print(f"  Vectors: {index.ntotal}")
    
    # ── Save Documents + Section Index ──
    docs_path = OUTPUT_DIR / "documents.json"
    with open(docs_path, "w", encoding="utf-8") as f:
        json.dump(all_documents, f, indent=2, ensure_ascii=False)
    print(f"✓ Documents saved: {docs_path}")
    
    section_index_path = OUTPUT_DIR / "section_index.json"
    with open(section_index_path, "w", encoding="utf-8") as f:
        json.dump(section_index, f, indent=2)
    print(f"✓ Section index saved: {section_index_path} ({len(section_index)} sections)")
    
    # ── Summary ──
    print(f"\n{'=' * 70}")
    print("  INGESTION COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Chapters processed: {len(pdf_files)}")
    print(f"  Total chunks:       {total_chunks}")
    print(f"  Total sections:     {total_sections}")
    print(f"  FAISS vectors:      {index.ntotal}")
    print(f"  ChromaDB docs:      {collection.count()}")
    print(f"  Section index keys: {len(section_index)}")
    print(f"\n  Output directory: {OUTPUT_DIR}")
    
    # Sample sections
    print("\n  Sample sections indexed:")
    for key in sorted(section_index.keys())[:10]:
        entries = section_index[key]
        label = entries[0].get("section_full", key)
        print(f"    {key}: {label} ({len(entries)} chunks)")
    
    print("\n✓ Done!")


if __name__ == "__main__":
    ingest_dgft_ftp()
