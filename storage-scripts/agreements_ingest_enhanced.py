"""
Enhanced Trade Agreements Ingestion for RAG-Ready Multi-Agent System

This script extracts PDF data from trade agreements and stores them in a format
optimized for Retrieval Augmented Generation (RAG) and multi-agent systems.

Features:
- Article-aware chunking that preserves legal document structure
- Cross-reference extraction (Article X.Y, Annex Z references)
- OCR text cleanup for noisy PDF extractions
- Smart handling of tariff schedule PDFs (skip or table-mode)
- Stores in both FAISS (vector search) and ChromaDB (metadata filtering)
- Rich metadata: country, doc_type, chapter, article, cross-references
"""

import os
import re
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

# PDF Processing
import fitz  # PyMuPDF - fast, reliable PDF text extraction
# unstructured is used as fallback for complex table PDFs

# Embeddings & Vector Stores
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import chromadb
from chromadb.config import Settings

# --- Configuration ---
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data" / "agreements"
OUTPUT_DIR = ROOT_DIR / "agreements_rag_store"
FAISS_INDEX_PATH = OUTPUT_DIR / "agreements.index"
CHROMA_DB_PATH = OUTPUT_DIR / "agreements_chroma"

# Chunk settings
MAX_CHUNK_CHARS = 1200      # Max characters per chunk
MIN_CHUNK_CHARS = 100       # Skip chunks smaller than this
OVERLAP_CHARS = 150         # Overlap between consecutive sub-chunks

# Files to SKIP entirely (massive tariff schedule tables - data already in PostgreSQL)
SKIP_PATTERNS = [
    "Schedule-Australia",
    "Schedule-India",
    "Schedule-of-Tariff",
    "Schedule-of-Commitment",
    "Schedule-of-Specific-Commitment",
    "Schedule-of-non-conforming",
    "Market-Access-Offer",
    "Tariff-Concessions",
    "Schedule-of-Specific-Commitments",  # services schedules (huge tables)
    "Schedules-of-Specific-Commitments",
    "Schedule-Government-Procurement",
]

# Create output directories
OUTPUT_DIR.mkdir(exist_ok=True)
CHROMA_DB_PATH.mkdir(exist_ok=True)

# Initialize Embedding Model
print("Loading embedding model...")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
EMBEDDING_DIM = 384  # Dimension for all-MiniLM-L6-v2

# Initialize ChromaDB
chroma_client = chromadb.PersistentClient(
    path=str(CHROMA_DB_PATH),
    settings=Settings(anonymized_telemetry=False)
)


# ──────────────────────────────────────────────────────────────
# OCR Cleanup
# ──────────────────────────────────────────────────────────────

# Common OCR errors found in UAE and other scanned PDFs
OCR_FIXES = {
    "ntanufaclure": "manufacture",
    "ntanufacture": "manufacture",
    "fiiaterial": "material",
    "materia!": "material",
    "financia!": "financial",
    "vesse!": "vessel",
    "Ioaded": "loaded",
    "Iater": "later",
    "Iive": "live",
    "lndia": "India",
    "lnternational": "International",
    "lssuing": "Issuing",
    "harUested": "harvested",
    "exctusivety": "exclusively",
    "!and": " and",       # "!and" at word boundary
    "Val uation": "Valuation",
    "Defin itions": "Definitions",
    "Ag reement": "Agreement",
    "proced ures": "procedures",
    "1CfC1": "(CTC)",
    "perArticle": "per Article",
}


def clean_ocr_text(text: str) -> str:
    """Fix common OCR errors in scanned PDF text"""
    for wrong, right in OCR_FIXES.items():
        text = text.replace(wrong, right)

    # Fix broken spacing around parenthetical references
    # e.g. "Article 3 .2" → "Article 3.2"
    text = re.sub(r'(Article\s+\d+)\s+\.(\d+)', r'\1.\2', text)

    # Fix double spaces
    text = re.sub(r'  +', ' ', text)

    # Fix spaced-out words common in OCR: "c o m m e r c e" patterns
    # (only fix if > 5 single chars in a row)
    text = re.sub(r'(?<= )(\w) (\w) (\w) (\w) (\w) (\w)', 
                  lambda m: ''.join(m.groups()), text)

    return text.strip()


# ──────────────────────────────────────────────────────────────
# Metadata Extraction
# ──────────────────────────────────────────────────────────────

def extract_document_metadata(pdf_path: Path, country: str) -> Dict[str, Any]:
    """Extract metadata from PDF filename and path"""
    filename = pdf_path.stem

    # Determine document type from filename
    fname_lower = filename.lower()
    if "annex" in fname_lower:
        doc_type = "annex"
    elif "schedule" in fname_lower:
        doc_type = "schedule"
    elif "chapter" in fname_lower:
        doc_type = "chapter"
    elif "letter" in fname_lower or "response" in fname_lower:
        doc_type = "correspondence"
    elif "faq" in fname_lower:
        doc_type = "faq"
    elif "synopsis" in fname_lower:
        doc_type = "synopsis"
    elif "preamble" in fname_lower:
        doc_type = "preamble"
    elif "contents" in fname_lower:
        doc_type = "table_of_contents"
    elif "taxation" in fname_lower:
        doc_type = "taxation"
    elif "trade" in fname_lower and "goods" in fname_lower:
        doc_type = "trade_in_goods"
    elif "rules" in fname_lower and "origin" in fname_lower:
        doc_type = "rules_of_origin"
    elif "services" in fname_lower:
        doc_type = "trade_in_services"
    elif "dispute" in fname_lower:
        doc_type = "dispute_settlement"
    elif "remedies" in fname_lower:
        doc_type = "trade_remedies"
    elif "sanitary" in fname_lower or "sps" in fname_lower:
        doc_type = "sps_measures"
    elif "technical" in fname_lower or "tbt" in fname_lower:
        doc_type = "tbt"
    elif "customs" in fname_lower or "cus" in fname_lower:
        doc_type = "customs"
    elif "transparency" in fname_lower:
        doc_type = "transparency"
    elif "intellectual" in fname_lower or "ipr" in fname_lower:
        doc_type = "intellectual_property"
    elif "digital" in fname_lower:
        doc_type = "digital_trade"
    elif "procurement" in fname_lower:
        doc_type = "government_procurement"
    elif "movement" in fname_lower:
        doc_type = "movement_of_persons"
    elif "financial" in fname_lower:
        doc_type = "financial_services"
    elif "telecom" in fname_lower:
        doc_type = "telecommunications"
    elif "professional" in fname_lower:
        doc_type = "professional_services"
    elif "investment" in fname_lower:
        doc_type = "investment"
    else:
        doc_type = "agreement"

    # Extract chapter/section number from filename
    chapter_num = None
    # Match patterns like "02-Trade", "Chapter-3", "04A-AN_1"
    num_match = re.match(r'^(?:Chapter[- ]?)?(\d+)', filename)
    if num_match:
        chapter_num = num_match.group(1)

    # Determine agreement name
    agreement_names = {
        "australia": "India-Australia ECTA (AI-ECTA)",
        "uae": "India-UAE CEPA",
        "uk": "India-UK CETA (FTA)",
    }

    return {
        "country": country,
        "agreement": agreement_names.get(country, f"India-{country.upper()} FTA"),
        "filename": pdf_path.name,
        "doc_type": doc_type,
        "chapter": chapter_num,
        "file_path": str(pdf_path.relative_to(ROOT_DIR)) if pdf_path.is_absolute() else str(pdf_path),
        "ingestion_date": datetime.now().isoformat(),
    }


# ──────────────────────────────────────────────────────────────
# Cross-Reference Extraction
# ──────────────────────────────────────────────────────────────

def extract_cross_references(text: str) -> Dict[str, List[str]]:
    """
    Extract cross-references from agreement text.
    
    These agreements heavily cross-reference each other, e.g.:
    - "as provided for in Article 4.4 (Wholly Obtained...)"
    - "pursuant to Annex 2A (Tariff Commitments)"
    - "in accordance with Chapter 3"
    """
    refs = {
        "articles": [],
        "annexes": [],
        "chapters": [],
        "paragraphs": [],
    }

    # Article references: "Article 4.3", "Article 3.2(b)"
    article_refs = re.findall(r'Article\s+(\d+\.\d+)(?:\s*\([^)]*\))?', text)
    refs["articles"] = sorted(set(article_refs))

    # Annex references: "Annex 2A", "Annex 4B", "Annex 3C"
    annex_refs = re.findall(r'Annex\s+(\w+)', text)
    refs["annexes"] = sorted(set(annex_refs))

    # Chapter references: "Chapter 3", "Chapter 14"
    chapter_refs = re.findall(r'Chapter\s+(\d+)', text)
    refs["chapters"] = sorted(set(chapter_refs))

    # Paragraph references: "paragraph 1", "paragraph 2(a)"
    para_refs = re.findall(r'paragraph\s+(\d+(?:\s*\([a-z]\))?)', text, re.IGNORECASE)
    refs["paragraphs"] = sorted(set(para_refs))

    return refs


# ──────────────────────────────────────────────────────────────
# Article-Aware Chunking
# ──────────────────────────────────────────────────────────────

def extract_pdf_text(pdf_path: Path) -> str:
    """Extract full text from PDF using PyMuPDF (fast, reliable)"""
    try:
        doc = fitz.open(str(pdf_path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()

        full_text = "\n\n".join(pages)
        return clean_ocr_text(full_text)
    except Exception as e:
        print(f"  ⚠️  PyMuPDF failed for {pdf_path.name}: {e}")
        return ""


def split_into_articles(text: str) -> List[Dict[str, Any]]:
    """
    Split agreement text into article-level chunks.
    
    Recognizes patterns like:
    - "Article 4.1\nDefinitions and Interpretation"
    - "ARTICLE 3.2\nOrigin Criteria"
    """

    # Pattern: "Article X.Y" or "ARTICLE X.Y" possibly followed by title on next line
    article_pattern = re.compile(
        r'(?:^|\n)\s*((?:Article|ARTICLE)\s+(\d+\.\d+)\s*\n\s*([^\n]*))',
        re.MULTILINE
    )

    matches = list(article_pattern.finditer(text))

    if not matches:
        # No articles found — return entire text as one chunk
        return [{
            "text": text.strip(),
            "article_id": None,
            "article_title": None,
            "article_full": None,
        }]

    articles = []

    for i, match in enumerate(matches):
        article_id = match.group(2)       # e.g. "4.1"
        article_title = match.group(3).strip()  # e.g. "Definitions and Interpretation"
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        article_text = text[start:end].strip()

        # Skip if too short (just a header with no content)
        if len(article_text) < MIN_CHUNK_CHARS:
            continue

        articles.append({
            "text": article_text,
            "article_id": article_id,
            "article_title": article_title,
            "article_full": f"Article {article_id}: {article_title}",
        })

    # Also capture any preamble text before the first article
    if matches and matches[0].start() > MIN_CHUNK_CHARS:
        preamble = text[:matches[0].start()].strip()
        if len(preamble) >= MIN_CHUNK_CHARS:
            articles.insert(0, {
                "text": preamble,
                "article_id": "preamble",
                "article_title": "Preamble / Header",
                "article_full": "Preamble",
            })

    return articles


def sub_chunk_with_overlap(text: str, max_chars: int = MAX_CHUNK_CHARS,
                           overlap: int = OVERLAP_CHARS) -> List[str]:
    """
    Split a long text into sub-chunks with overlap.
    
    Tries to split at paragraph/sentence boundaries for cleaner chunks.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + max_chars

        if end >= len(text):
            chunks.append(text[start:].strip())
            break

        # Try to find a good break point (paragraph, sentence, or clause)
        chunk_text = text[start:end]

        # Prefer paragraph break
        last_para = chunk_text.rfind('\n\n')
        if last_para > max_chars * 0.4:
            end = start + last_para + 2
        else:
            # Try sentence boundary
            last_period = chunk_text.rfind('. ')
            if last_period > max_chars * 0.4:
                end = start + last_period + 2
            else:
                # Try semicolon / clause boundary
                last_semi = chunk_text.rfind('; ')
                if last_semi > max_chars * 0.4:
                    end = start + last_semi + 2

        chunks.append(text[start:end].strip())
        start = end - overlap  # overlap for continuity

    return [c for c in chunks if len(c) >= MIN_CHUNK_CHARS]


def chunk_document(text: str, doc_metadata: Dict) -> List[Dict[str, Any]]:
    """
    Main chunking pipeline:
    1. Split into articles
    2. Sub-chunk large articles with overlap
    3. Extract cross-references for each chunk
    4. Attach rich metadata
    """
    articles = split_into_articles(text)
    all_chunks = []
    chunk_idx = 0

    for article in articles:
        article_text = article["text"]
        sub_chunks = sub_chunk_with_overlap(article_text)

        for sub_idx, chunk_text in enumerate(sub_chunks):
            # Extract cross-references in this chunk
            refs = extract_cross_references(chunk_text)

            chunk_data = {
                "text": chunk_text,
                "metadata": {
                    **doc_metadata,
                    "chunk_id": chunk_idx,
                    "article_id": article["article_id"],
                    "article_title": article["article_title"],
                    "article_full": article["article_full"],
                    "sub_chunk": sub_idx if len(sub_chunks) > 1 else 0,
                    "total_sub_chunks": len(sub_chunks),
                    "text_length": len(chunk_text),
                    "cross_ref_articles": ",".join(refs["articles"]) if refs["articles"] else "",
                    "cross_ref_annexes": ",".join(refs["annexes"]) if refs["annexes"] else "",
                    "cross_ref_chapters": ",".join(refs["chapters"]) if refs["chapters"] else "",
                    "has_cross_refs": bool(refs["articles"] or refs["annexes"]),
                }
            }
            all_chunks.append(chunk_data)
            chunk_idx += 1

    return all_chunks


# ──────────────────────────────────────────────────────────────
# File Filtering
# ──────────────────────────────────────────────────────────────

def should_skip_file(pdf_path: Path) -> Tuple[bool, str]:
    """
    Determine if a PDF should be skipped.
    Returns (should_skip, reason).
    """
    filename = pdf_path.stem
    file_size_mb = pdf_path.stat().st_size / (1024 * 1024)

    # Skip files matching known tariff schedule patterns
    for pattern in SKIP_PATTERNS:
        if pattern.lower() in filename.lower():
            return True, f"tariff/schedule table ({file_size_mb:.1f} MB)"

    # Skip extremely large files (> 5MB) that aren't in the skip list
    # These are almost certainly table-heavy documents
    if file_size_mb > 8:
        return True, f"too large ({file_size_mb:.1f} MB), likely tables"

    # Skip table of contents (minimal useful info)
    if "table-of-contents" in filename.lower() or "contents" in filename.lower():
        return True, "table of contents"

    return False, ""


# ──────────────────────────────────────────────────────────────
# ID Generation
# ──────────────────────────────────────────────────────────────

def generate_chunk_id(text: str, doc_metadata: Dict) -> str:
    """Generate unique, deterministic ID for a chunk"""
    content = f"{doc_metadata['country']}_{doc_metadata['filename']}_{doc_metadata.get('article_id', '')}_{text[:200]}"
    return hashlib.md5(content.encode()).hexdigest()


# ──────────────────────────────────────────────────────────────
# Main Ingestion Pipeline
# ──────────────────────────────────────────────────────────────

def ingest_agreements():
    """Main ingestion pipeline"""
    print("=" * 70)
    print("  ENHANCED TRADE AGREEMENTS INGESTION")
    print("  Article-aware | Cross-references | OCR cleanup")
    print("=" * 70)

    # Storage
    all_embeddings = []
    all_documents = []
    chunk_id_to_index = {}

    # ChromaDB collection - recreate fresh
    try:
        chroma_client.delete_collection("trade_agreements")
    except Exception:
        pass

    collection = chroma_client.create_collection(
        name="trade_agreements",
        metadata={
            "description": "Trade agreements between India and partner countries",
            "features": "article-aware chunking, cross-references, OCR cleanup",
        }
    )

    global_idx = 0
    stats = {
        "total_docs": 0,
        "total_chunks": 0,
        "skipped_docs": 0,
        "by_country": {},
        "articles_parsed": 0,
        "cross_refs_found": 0,
    }

    # Process each country folder
    for country_folder in sorted(DATA_DIR.iterdir()):
        if not country_folder.is_dir():
            continue

        country_name = country_folder.name
        print(f"\n{'=' * 70}")
        print(f"  COUNTRY: {country_name.upper()}")
        print(f"{'=' * 70}")

        stats["by_country"][country_name] = {"docs": 0, "chunks": 0, "skipped": 0}
        pdf_files = list(country_folder.glob("*.pdf"))

        for pdf_idx, pdf_file in enumerate(sorted(pdf_files), 1):
            # Check if we should skip this file
            skip, reason = should_skip_file(pdf_file)
            if skip:
                print(f"  [{pdf_idx}/{len(pdf_files)}] SKIP: {pdf_file.name} ({reason})")
                stats["skipped_docs"] += 1
                stats["by_country"][country_name]["skipped"] += 1
                continue

            file_size_mb = pdf_file.stat().st_size / (1024 * 1024)
            print(f"  [{pdf_idx}/{len(pdf_files)}] {pdf_file.name} ({file_size_mb:.1f} MB)")

            # Extract document metadata
            doc_metadata = extract_document_metadata(pdf_file, country_name)

            # Extract text from PDF
            full_text = extract_pdf_text(pdf_file)
            if not full_text or len(full_text) < MIN_CHUNK_CHARS:
                print(f"    ⚠️  No usable text extracted, skipping")
                continue

            # Chunk with article-awareness
            content_chunks = chunk_document(full_text, doc_metadata)

            if not content_chunks:
                print(f"    ⚠️  No chunks produced, skipping")
                continue

            stats["total_docs"] += 1
            stats["by_country"][country_name]["docs"] += 1

            # Count articles found
            article_ids = set()
            chunk_cross_refs = 0

            # Process each chunk
            batch_ids = []
            batch_embeddings = []
            batch_documents = []
            batch_metadatas = []

            for chunk_data in content_chunks:
                chunk_text = chunk_data["text"]
                chunk_meta = chunk_data["metadata"]

                # Track stats
                if chunk_meta.get("article_id") and chunk_meta["article_id"] != "preamble":
                    article_ids.add(chunk_meta["article_id"])
                if chunk_meta.get("has_cross_refs"):
                    chunk_cross_refs += 1

                # Generate embedding
                embedding = embedding_model.encode(chunk_text, convert_to_numpy=True)

                # Generate unique ID
                chunk_id = generate_chunk_id(chunk_text, chunk_meta)

                # Store for FAISS
                all_embeddings.append(embedding)
                all_documents.append({
                    "id": chunk_id,
                    "text": chunk_text,
                    "metadata": chunk_meta,
                    "vector_index": global_idx,
                })
                chunk_id_to_index[chunk_id] = global_idx

                # Batch for ChromaDB (more efficient than one-at-a-time)
                # ChromaDB needs all metadata values as strings
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
                stats["total_chunks"] += 1
                stats["by_country"][country_name]["chunks"] += 1

            # Batch insert to ChromaDB
            if batch_ids:
                # ChromaDB has a batch limit, process in groups of 100
                for batch_start in range(0, len(batch_ids), 100):
                    batch_end = batch_start + 100
                    collection.add(
                        ids=batch_ids[batch_start:batch_end],
                        embeddings=batch_embeddings[batch_start:batch_end],
                        documents=batch_documents[batch_start:batch_end],
                        metadatas=batch_metadatas[batch_start:batch_end],
                    )

            stats["articles_parsed"] += len(article_ids)
            stats["cross_refs_found"] += chunk_cross_refs

            print(f"    ✓ {len(content_chunks)} chunks | "
                  f"{len(article_ids)} articles | "
                  f"{chunk_cross_refs} chunks with cross-refs")

    # ── Save FAISS index ──
    print(f"\n{'=' * 70}")
    print("  BUILDING FAISS INDEX")
    print(f"{'=' * 70}")

    if all_embeddings:
        embeddings_array = np.array(all_embeddings).astype('float32')

        # Normalize embeddings for cosine similarity via inner product
        faiss.normalize_L2(embeddings_array)
        index = faiss.IndexFlatIP(EMBEDDING_DIM)  # Inner Product after L2 norm = cosine sim
        index.add(embeddings_array)

        faiss.write_index(index, str(FAISS_INDEX_PATH))
        print(f"  ✓ FAISS index saved: {FAISS_INDEX_PATH}")
        print(f"    Index type: FlatIP (cosine similarity via normalized L2)")
        print(f"    Vectors: {index.ntotal}")

        # Save document store
        documents_path = OUTPUT_DIR / "documents.json"
        with open(documents_path, "w", encoding="utf-8") as f:
            json.dump(all_documents, f, indent=2, ensure_ascii=False)
        print(f"  ✓ Documents saved: {documents_path}")

        # Save index mapping
        mapping_path = OUTPUT_DIR / "chunk_id_mapping.json"
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(chunk_id_to_index, f, indent=2)
        print(f"  ✓ Chunk mapping saved: {mapping_path}")

        # Build article → chunk index for cross-reference resolution
        article_index = {}  # "australia_4.1" → [chunk_ids]
        for doc in all_documents:
            meta = doc["metadata"]
            article_id = meta.get("article_id")
            country = meta.get("country")
            if article_id and article_id != "preamble":
                key = f"{country}_{article_id}"
                if key not in article_index:
                    article_index[key] = []
                article_index[key].append({
                    "chunk_id": doc["id"],
                    "vector_index": doc["vector_index"],
                    "article_full": meta.get("article_full", ""),
                    "filename": meta.get("filename", ""),
                })

        article_index_path = OUTPUT_DIR / "article_index.json"
        with open(article_index_path, "w", encoding="utf-8") as f:
            json.dump(article_index, f, indent=2, ensure_ascii=False)
        print(f"  ✓ Article cross-ref index saved: {article_index_path}")
        print(f"    Indexed articles: {len(article_index)}")

    # Save ingestion statistics
    stats["timestamp"] = datetime.now().isoformat()
    stats_path = OUTPUT_DIR / "ingestion_stats.json"
    with open(stats_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    # ── Print Summary ──
    print(f"\n{'=' * 70}")
    print("  ✅ INGESTION COMPLETE!")
    print(f"{'=' * 70}")
    print(f"  Total Documents Processed: {stats['total_docs']}")
    print(f"  Total Documents Skipped:   {stats['skipped_docs']} (tariff schedules / tables)")
    print(f"  Total Chunks Created:      {stats['total_chunks']}")
    print(f"  Total Articles Parsed:     {stats['articles_parsed']}")
    print(f"  Chunks with Cross-Refs:    {stats['cross_refs_found']}")
    print(f"\n  Breakdown by Country:")
    for country, counts in stats["by_country"].items():
        print(f"    {country.upper():12s}: {counts['docs']:3d} docs, "
              f"{counts['chunks']:5d} chunks, "
              f"{counts.get('skipped', 0):3d} skipped")
    print(f"\n  Output Location: {OUTPUT_DIR}")
    print(f"    - FAISS Index:       {FAISS_INDEX_PATH.name}")
    print(f"    - ChromaDB:          {CHROMA_DB_PATH.name}/")
    print(f"    - Documents:         documents.json")
    print(f"    - Article Index:     article_index.json")
    print(f"    - Statistics:        ingestion_stats.json")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    ingest_agreements()
