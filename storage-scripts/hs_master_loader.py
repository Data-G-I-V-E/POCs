"""
HS Master 8-Digit Code Loader
Extracts HS codes from master_hs_codes.pdf and loads into PostgreSQL.

Usage:
    python storage-scripts/hs_master_loader.py
"""

import re
import sys
import pdfplumber
import psycopg2
from pathlib import Path
from tqdm import tqdm

# Add parent dir to path for config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config


def _clean_cell(text: str) -> str:
    """Normalize cell text: collapse whitespace/newlines, strip leading/trailing spaces."""
    if not text:
        return ""
    return " ".join(text.split()).strip()


def _is_int(val: str) -> bool:
    try:
        int(str(val).strip())
        return True
    except (ValueError, TypeError):
        return False


def extract_hs_codes_from_pdf(pdf_path: str) -> list[dict]:
    """
    Extract all HS code rows from the PDF.

    Primary strategy: pdfplumber extract_tables() — correctly captures multi-line
    cell content (e.g. a description spanning 4 lines in the PDF becomes one string).

    Fallback strategy: line-by-line regex on extract_text() for pages where table
    extraction yields nothing (some pages render as plain text rather than tables).
    """

    pdf = pdfplumber.open(pdf_path)
    total_pages = len(pdf.pages)
    print(f"📄 Opened PDF: {total_pages} pages")

    # Fallback regex (only used when table extraction fails for a page)
    row_pattern = re.compile(
        r'^\s*(\d{1,5})\s+'
        r'(\d{1,3})\s+'
        r'(\d{7,8})\s+'
        r'(.+?)$',
        re.MULTILINE
    )

    all_rows = []
    table_pages = 0
    fallback_pages = 0

    for page_num in tqdm(range(total_pages), desc="Extracting pages"):
        page = pdf.pages[page_num]

        # ── Primary: table extraction ──────────────────────────────────────────
        tables = page.extract_tables()
        page_rows_from_tables = []

        for table in tables:
            for row in table:
                if not row or len(row) < 4:
                    continue
                s_no_raw  = _clean_cell(str(row[0]))
                ch_raw    = _clean_cell(str(row[1]))
                code_raw  = _clean_cell(str(row[2]))
                desc_raw  = _clean_cell(str(row[3])) if row[3] else ""

                # Skip header rows and rows without valid numeric fields
                if not (_is_int(s_no_raw) and _is_int(ch_raw)):
                    continue
                if not re.match(r'^\d{7,8}$', code_raw):
                    continue
                if not desc_raw:
                    continue

                # Strip trailing category column if it leaked into description
                # e.g. "OTHR REDIO-BROADCST ... D/o Telecommunications" → drop after "D/o"
                desc_clean = re.sub(r'\s+D/[Oo]\b.*$', '', desc_raw).strip()

                page_rows_from_tables.append({
                    's_no': int(s_no_raw),
                    'chapter': int(ch_raw),
                    'hs_code': code_raw,
                    'description': desc_clean.upper().strip()
                })

        if page_rows_from_tables:
            all_rows.extend(page_rows_from_tables)
            table_pages += 1
            continue

        # ── Fallback: line-by-line regex on plain text ─────────────────────────
        text = page.extract_text()
        if not text:
            continue

        matches = row_pattern.findall(text)
        if matches:
            fallback_pages += 1
        for match in matches:
            s_no, chapter, hs_code, description = match
            description = description.strip()
            all_rows.append({
                's_no': int(s_no),
                'chapter': int(chapter),
                'hs_code': hs_code.strip(),
                'description': description.upper().strip()
            })

    pdf.close()
    print(f"✅ Extracted {len(all_rows)} HS code rows "
          f"({table_pages} pages via tables, {fallback_pages} pages via text fallback)")
    return all_rows


def create_table(cursor):
    """Create the hs_master_8_digit table."""
    cursor.execute("DROP TABLE IF EXISTS hs_master_8_digit CASCADE;")
    cursor.execute("""
        CREATE TABLE hs_master_8_digit (
            id SERIAL PRIMARY KEY,
            s_no INTEGER,
            chapter INTEGER NOT NULL,
            hs_code VARCHAR(10) NOT NULL,
            description TEXT NOT NULL,
            chapter_code VARCHAR(2) GENERATED ALWAYS AS (LPAD(chapter::text, 2, '0')) STORED
        );
    """)
    print("✅ Created table hs_master_8_digit")


def create_indexes(cursor):
    """Create indexes for fast lookup."""
    print("📇 Creating indexes...")
    cursor.execute("CREATE INDEX idx_hs_master_code ON hs_master_8_digit(hs_code);")
    cursor.execute("CREATE INDEX idx_hs_master_chapter ON hs_master_8_digit(chapter);")
    cursor.execute("CREATE INDEX idx_hs_master_desc_gin ON hs_master_8_digit USING gin(to_tsvector('english', description));")
    cursor.execute("CREATE INDEX idx_hs_master_desc_trgm ON hs_master_8_digit USING gin(description gin_trgm_ops);")
    print("✅ Created indexes (btree on hs_code, chapter; GIN on description for full-text + trigram)")


def insert_rows(cursor, rows: list[dict]):
    """Bulk insert rows into the table."""
    print(f"📥 Inserting {len(rows)} rows...")
    
    # Use executemany with batch insert
    insert_sql = """
        INSERT INTO hs_master_8_digit (s_no, chapter, hs_code, description)
        VALUES (%s, %s, %s, %s)
    """
    
    batch = [(r['s_no'], r['chapter'], r['hs_code'], r['description']) for r in rows]
    
    # Insert in chunks of 1000
    chunk_size = 1000
    for i in range(0, len(batch), chunk_size):
        chunk = batch[i:i + chunk_size]
        cursor.executemany(insert_sql, chunk)
    
    print(f"✅ Inserted {len(rows)} rows")


def verify_data(cursor):
    """Print verification stats."""
    print("\n" + "=" * 60)
    print("VERIFICATION")
    print("=" * 60)
    
    cursor.execute("SELECT COUNT(*) FROM hs_master_8_digit;")
    total = cursor.fetchone()[0]
    print(f"Total rows: {total}")
    
    cursor.execute("SELECT COUNT(DISTINCT chapter) FROM hs_master_8_digit;")
    chapters = cursor.fetchone()[0]
    print(f"Distinct chapters: {chapters}")
    
    cursor.execute("SELECT COUNT(DISTINCT hs_code) FROM hs_master_8_digit;")
    unique_codes = cursor.fetchone()[0]
    print(f"Unique HS codes: {unique_codes}")
    
    cursor.execute("""
        SELECT chapter, COUNT(*) as cnt 
        FROM hs_master_8_digit 
        GROUP BY chapter 
        ORDER BY chapter 
        LIMIT 10;
    """)
    print("\nTop 10 chapters by row count:")
    for row in cursor.fetchall():
        print(f"  Chapter {row[0]:3d}: {row[1]} codes")
    
    cursor.execute("SELECT s_no, chapter, hs_code, description FROM hs_master_8_digit LIMIT 5;")
    print("\nFirst 5 rows:")
    for row in cursor.fetchall():
        print(f"  S.No {row[0]}: Ch-{row[1]}, HS {row[2]}, {row[3][:60]}")
    
    cursor.execute("SELECT s_no, chapter, hs_code, description FROM hs_master_8_digit ORDER BY s_no DESC LIMIT 3;")
    print("\nLast 3 rows:")
    for row in cursor.fetchall():
        print(f"  S.No {row[0]}: Ch-{row[1]}, HS {row[2]}, {row[3][:60]}")
    
    # Test full-text search
    cursor.execute("""
        SELECT hs_code, description 
        FROM hs_master_8_digit 
        WHERE to_tsvector('english', description) @@ plainto_tsquery('english', 'roses')
        LIMIT 5;
    """)
    results = cursor.fetchall()
    print(f"\nFull-text search for 'roses': {len(results)} results")
    for row in results:
        print(f"  HS {row[0]}: {row[1][:60]}")


def main():
    pdf_path = Path(__file__).parent.parent / "data" / "master_hs_codes.pdf"
    if not pdf_path.exists():
        print(f"❌ PDF not found: {pdf_path}")
        return
    
    print("=" * 60)
    print("HS MASTER 8-DIGIT CODE LOADER")
    print("=" * 60)
    
    # Step 1: Extract from PDF
    rows = extract_hs_codes_from_pdf(str(pdf_path))
    if not rows:
        print("❌ No rows extracted!")
        return
    
    # Step 2: Load into PostgreSQL
    print(f"\n📊 Connecting to database...")
    conn = psycopg2.connect(**Config.DB_CONFIG)
    cursor = conn.cursor()
    
    try:
        # Enable trigram extension (for fuzzy search)
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        conn.commit()
        
        create_table(cursor)
        conn.commit()
        
        insert_rows(cursor, rows)
        conn.commit()
        
        create_indexes(cursor)
        conn.commit()
        
        verify_data(cursor)
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()
    
    print("\n✅ Done! Table hs_master_8_digit is ready.")


if __name__ == "__main__":
    main()
