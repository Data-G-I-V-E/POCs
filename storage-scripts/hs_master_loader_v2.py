"""
HS Master Code Loader v2 — Uses `unstructured` library for better PDF table extraction.

Source: data/master_hs_codes.pdf  (single master file, 4 columns: S.No / Chapter / HS Code / Description)

Improvements over v1 (hs_master_loader.py):
  - unstructured infer_table_structure → much better multi-line cell joining
  - Abbreviation expansion map → BROADCST→BROADCAST, OTHR→OTHER, etc., so full-text search works
  - New schema columns: code_level, parent_code, heading, subheading, UNIQUE on hs_code
  - GIN full-text + trigram indexes on description

Usage:
    python storage-scripts/hs_master_loader_v2.py
"""

import re
import sys
import psycopg2
from pathlib import Path
from typing import Optional

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config

# ── Try unstructured (preferred) ──────────────────────────────────────────────
try:
    from unstructured.partition.pdf import partition_pdf
    from unstructured.documents.elements import Table as UTable
    HAVE_UNSTRUCTURED = True
except ImportError:
    HAVE_UNSTRUCTURED = False

# ── Always available fallback ──────────────────────────────────────────────────
import pdfplumber
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
MASTER_PDF = Path(__file__).parent.parent / "data" / "master_hs_codes.pdf"

# Common abbreviations found in Indian tariff PDFs; expand them so FTS works.
ABBREV_EXPANSIONS = {
    r'\bOTHR\b':          'OTHER',
    r'\bOTH\b':           'OTHER',
    r'\bPREP\b':          'PREPARED',
    r'\bFRSH\b':          'FRESH',
    r'\bFRZN\b':          'FROZEN',
    r'\bDRD\b':           'DRIED',
    r'\bMFRD\b':          'MANUFACTURED',
    r'\bWHTHR\b':         'WHETHER',
    r'\bINCLD\b':         'INCLUDING',
    r'\bNES\b':           'NOT ELSEWHERE SPECIFIED',
    r'\bNEC\b':           'NOT ELSEWHERE CLASSIFIED',
    r'\bW/O\b':           'WITHOUT',
    r'\bW/\b':            'WITH',
    r'\bELCTRCL\b':       'ELECTRICAL',
    r'\bELECTRN\b':       'ELECTRONIC',
    r'\bTLCMM\b':         'TELECOMMUNICATION',
    r'\bTLPHN\b':         'TELEPHONE',
    r'\bBROADCST\b':      'BROADCAST',
    r'\bBRDCST\b':        'BROADCAST',
    r'\bRCVRS\b':         'RECEIVERS',
    r'\bTRNSMTR\b':       'TRANSMITTERS',
    r'\bAPPRTS\b':        'APPARATUS',
    r'\bINSTRMNT\b':      'INSTRUMENT',
    r'\bPRFSSNL\b':       'PROFESSIONAL',
    r'\bMDCL\b':          'MEDICAL',
    r'\bSRGCL\b':         'SURGICAL',
    r'\bDNTL\b':          'DENTAL',
    r'\bPHTGRPHC\b':      'PHOTOGRAPHIC',
    r'\bCNMTGRPHC\b':     'CINEMATOGRAPHIC',
    r'\bGRMNTS\b':        'GARMENTS',
    r'\bKNTD\b':          'KNITTED',
    r'\bWVN\b':           'WOVEN',
    r'\bCRCHTD\b':        'CROCHETED',
    r'\bCTN\b':           'COTTON',
    r'\bSNTHTC\b':        'SYNTHETIC',
    r'\bMNMD\b':          'MAN-MADE',
    r'\bFBRS\b':          'FIBRES',
    r'\bYRN\b':           'YARN',
    r'\bTXTL\b':          'TEXTILE',
    r'\bACCSRS\b':        'ACCESSORIES',
    r'\bAPPRL\b':         'APPAREL',
    r'\bCLTHNG\b':        'CLOTHING',
    r'\bVGTBLS\b':        'VEGETABLES',
    r'\bFRTS\b':          'FRUITS',
    r'\bNTS\b':           'NUTS',
    r'\bEDBL\b':          'EDIBLE',
    r'\bFRSH\b':          'FRESH',
    r'\bCHLLD\b':         'CHILLED',
    r'\bFRZN\b':          'FROZEN',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_code(raw: str) -> Optional[str]:
    """Strip dots / spaces; return if 4–8 pure digits, else None."""
    code = re.sub(r'[\s\.]', '', str(raw)).strip()
    return code if re.match(r'^\d{4,8}$', code) else None


def _code_level(code: str) -> int:
    n = len(code)
    if n <= 4:
        return 1   # heading
    if n <= 6:
        return 2   # subheading
    return 3       # 8-digit tariff line


def _parent_code(code: str) -> Optional[str]:
    n = len(code)
    if n == 8:
        return code[:6]
    if n == 6:
        return code[:4]
    return None


def _normalize_description(text: str) -> str:
    """Expand abbreviations, title-case, collapse whitespace."""
    t = re.sub(r'\s+', ' ', text).strip()
    for pattern, replacement in ABBREV_EXPANSIONS.items():
        t = re.sub(pattern, replacement, t, flags=re.IGNORECASE)
    # Title case but preserve existing uppercase acronyms >3 chars
    words = []
    for w in t.split():
        if w.isupper() and len(w) > 3:
            words.append(w)                # keep as uppercase acronym
        else:
            words.append(w.capitalize())
    return ' '.join(words)


def _is_header_row(cells: list[str]) -> bool:
    """Detect header rows that should be skipped."""
    joined = ' '.join(cells).lower()
    return any(kw in joined for kw in ('hs code', 'description', 'chapter', 's.no', 'serial', 'unit'))


def _parse_row(cells: list[str]) -> Optional[dict]:
    """
    Given a table row, find the HS code cell (7-8 digits) and the adjacent
    description cell.  Also pick up chapter from an adjacent numeric cell.
    Return a dict or None if the row doesn't look like an HS entry.
    """
    hs_code = None
    description = None
    chapter = None

    for i, cell in enumerate(cells):
        code = _clean_code(cell)
        if code and re.match(r'^\d{7,8}$', code):
            hs_code = code
            # chapter = first 2 digits of hs_code
            chapter = int(code[:2])
            # description = next non-empty, non-code cell
            for j in range(i + 1, len(cells)):
                candidate = re.sub(r'\s+', ' ', cells[j]).strip()
                # Strip trailing "D/o ..." category noise
                candidate = re.sub(r'\s+D/[Oo]\b.*$', '', candidate).strip()
                if candidate and not _clean_code(candidate) and len(candidate) > 4:
                    description = candidate
                    break
            break

    if hs_code and description and chapter:
        return {
            'chapter':     chapter,
            'hs_code':     hs_code,
            'description': description,
            'code_level':  _code_level(hs_code),
            'parent_code': _parent_code(hs_code),
        }
    return None


# ---------------------------------------------------------------------------
# Extraction — unstructured (primary)
# ---------------------------------------------------------------------------

def _extract_unstructured(pdf_path: str) -> list[dict]:
    """Partition the master PDF and parse every HTML table element."""
    rows: list[dict] = []
    elements = partition_pdf(
        filename=str(pdf_path),
        strategy="auto",
        infer_table_structure=True,
    )

    for el in elements:
        html = getattr(getattr(el, 'metadata', None), 'text_as_html', None)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for tr in soup.find_all('tr'):
            cells = [td.get_text(separator=' ', strip=True)
                     for td in tr.find_all(['td', 'th'])]  # type: ignore[union-attr]
            if len(cells) < 2 or _is_header_row(cells):
                continue
            entry = _parse_row(cells)
            if entry:
                rows.append(entry)
    return rows


# ---------------------------------------------------------------------------
# Extraction — pdfplumber (fallback)
# ---------------------------------------------------------------------------

def _extract_pdfplumber(pdf_path: str) -> list[dict]:
    """Extract tables page-by-page; fall back to line regex on text-only pages."""
    rows: list[dict] = []
    # Regex for plain-text pages: s_no chapter hs_code description
    line_re = re.compile(
        r'^\s*\d+\s+\d{1,2}\s+(?P<code>\d{7,8})\s+(?P<desc>.{5,})$'
    )

    with pdfplumber.open(pdf_path) as pdf:
        print(f"  📄 pdfplumber: {len(pdf.pages)} pages...")
        for page in tqdm(pdf.pages, desc="  Pages", leave=False):
            tables = page.extract_tables()
            for table in tables:
                for raw_row in (table or []):
                    if not raw_row:
                        continue
                    cells = [str(c).strip() if c else '' for c in raw_row]
                    if _is_header_row(cells):
                        continue
                    entry = _parse_row(cells)
                    if entry:
                        rows.append(entry)

            if not tables:
                text = page.extract_text() or ''
                for line in text.splitlines():
                    m = line_re.match(line.strip())
                    if m:
                        code = _clean_code(m.group('code'))
                        if code:
                            desc = re.sub(r'\s+', ' ', m.group('desc')).strip()
                            desc = re.sub(r'\s+D/[Oo]\b.*$', '', desc).strip()
                            if desc and not _clean_code(desc):
                                rows.append({
                                    'chapter':     int(code[:2]),
                                    'hs_code':     code,
                                    'description': desc,
                                    'code_level':  _code_level(code),
                                    'parent_code': _parent_code(code),
                                })
    return rows


# ---------------------------------------------------------------------------
# Main extraction dispatcher
# ---------------------------------------------------------------------------

def extract_master_pdf(pdf_path: str) -> list[dict]:
    """Try unstructured first; fall back to pdfplumber."""
    rows: list[dict] = []

    if HAVE_UNSTRUCTURED:
        try:
            print("  🔬 unstructured extraction...")
            rows = _extract_unstructured(pdf_path)
            print(f"  → {len(rows)} rows via unstructured")
        except Exception as e:
            print(f"  ⚠️  unstructured error: {e}")

    if not rows:
        rows = _extract_pdfplumber(pdf_path)
        print(f"  → {len(rows)} rows via pdfplumber")

    # Expand abbreviations in descriptions
    for r in rows:
        r['description'] = _normalize_description(r['description'])

    # Deduplicate by hs_code — keep highest code_level entry (most specific)
    best: dict[str, dict] = {}
    for r in rows:
        key = r['hs_code']
        if key not in best or r['code_level'] > best[key]['code_level']:
            best[key] = r

    deduped = list(best.values())
    print(f"  ✅ {len(deduped)} unique HS codes after deduplication")
    return deduped


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def create_table(cursor):
    cursor.execute("DROP TABLE IF EXISTS hs_master_8_digit CASCADE;")
    cursor.execute("""
        CREATE TABLE hs_master_8_digit (
            id           SERIAL PRIMARY KEY,
            chapter      INTEGER NOT NULL,
            hs_code      VARCHAR(10) NOT NULL,
            heading      VARCHAR(4),
            subheading   VARCHAR(6),
            description  TEXT NOT NULL,
            code_level   INTEGER NOT NULL DEFAULT 3,
            parent_code  VARCHAR(10),
            source_chapter VARCHAR(2) GENERATED ALWAYS AS (LPAD(chapter::TEXT, 2, '0')) STORED,
            CONSTRAINT uq_hs_code UNIQUE (hs_code)
        );
    """)
    print("✅ Table hs_master_8_digit created")


def create_indexes(cursor):
    print("📇 Creating indexes...")
    cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    cursor.execute("CREATE INDEX idx_hs_m_chapter  ON hs_master_8_digit (chapter);")
    cursor.execute("CREATE INDEX idx_hs_m_heading  ON hs_master_8_digit (heading);")
    cursor.execute("CREATE INDEX idx_hs_m_level    ON hs_master_8_digit (code_level);")
    cursor.execute("CREATE INDEX idx_hs_m_parent   ON hs_master_8_digit (parent_code);")
    cursor.execute(
        "CREATE INDEX idx_hs_m_fts   ON hs_master_8_digit "
        "USING gin(to_tsvector('english', description));"
    )
    cursor.execute(
        "CREATE INDEX idx_hs_m_trgm  ON hs_master_8_digit "
        "USING gin(description gin_trgm_ops);"
    )
    print("✅ Indexes created")


def insert_rows(cursor, rows: list[dict]):
    sql = """
        INSERT INTO hs_master_8_digit
            (chapter, hs_code, heading, subheading, description, code_level, parent_code)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (hs_code) DO UPDATE
            SET description  = EXCLUDED.description,
                code_level   = EXCLUDED.code_level,
                parent_code  = EXCLUDED.parent_code
    """
    batch = [
        (
            r['chapter'],
            r['hs_code'],
            r['hs_code'][:4] if len(r['hs_code']) >= 4 else None,
            r['hs_code'][:6] if len(r['hs_code']) >= 6 else None,
            r['description'],
            r['code_level'],
            r['parent_code'],
        )
        for r in rows
    ]
    for i in range(0, len(batch), 500):
        cursor.executemany(sql, batch[i:i + 500])
    print(f"📥 Inserted / updated {len(rows)} rows")


def verify(cursor):
    print("\n" + "=" * 55)
    print("VERIFICATION")
    print("=" * 55)

    cursor.execute("SELECT COUNT(*) FROM hs_master_8_digit;")
    print(f"Total rows          : {cursor.fetchone()[0]}")

    cursor.execute("SELECT COUNT(DISTINCT chapter) FROM hs_master_8_digit;")
    print(f"Distinct chapters   : {cursor.fetchone()[0]}")

    cursor.execute("SELECT COUNT(*) FROM hs_master_8_digit WHERE code_level = 1;")
    print(f"Headings (4-digit)  : {cursor.fetchone()[0]}")

    cursor.execute("SELECT COUNT(*) FROM hs_master_8_digit WHERE code_level = 2;")
    print(f"Subheadings (6-dig) : {cursor.fetchone()[0]}")

    cursor.execute("SELECT COUNT(*) FROM hs_master_8_digit WHERE code_level = 3;")
    print(f"Tariff lines (8-dig): {cursor.fetchone()[0]}")

    # Spot-check FTS
    for kw in ('onions', 'garments', 'electrical', 't-shirts'):
        cursor.execute(
            """SELECT COUNT(*) FROM hs_master_8_digit
               WHERE to_tsvector('english', description) @@ plainto_tsquery('english', %s)""",
            (kw,)
        )
        n = cursor.fetchone()[0]
        print(f"FTS '{kw}' matches   : {n}")

    # Sample rows
    cursor.execute(
        "SELECT chapter, hs_code, code_level, description FROM hs_master_8_digit ORDER BY hs_code LIMIT 8;"
    )
    print("\nSample rows:")
    for r in cursor.fetchall():
        level_label = {1: 'heading', 2: 'subheading', 3: 'tariff'}.get(r[2], '?')
        print(f"  Ch-{r[0]:02d}  HS {r[1]}  [{level_label}]  {r[3][:60]}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 55)
    print("HS MASTER CODE LOADER v2  (unstructured + pdfplumber)")
    print("=" * 55)

    if HAVE_UNSTRUCTURED:
        print("✅ unstructured library available — will try first")
    else:
        print("⚠️  unstructured not installed — using pdfplumber only")
        print("   To install: pip install 'unstructured[pdf]'")

    if not MASTER_PDF.exists():
        print(f"❌ Master PDF not found: {MASTER_PDF}")
        return

    print(f"\n📘 Source: {MASTER_PDF}")
    all_rows = extract_master_pdf(str(MASTER_PDF))

    if not all_rows:
        print("\n❌ No rows extracted! Check PDF format or paths.")
        return

    print(f"\n📊 Grand total: {len(all_rows)} HS code entries")

    conn = psycopg2.connect(**Config.DB_CONFIG)
    cursor = conn.cursor()
    try:
        create_table(cursor)
        create_indexes(cursor)
        insert_rows(cursor, all_rows)
        conn.commit()
        verify(cursor)
        print("\n✅ Done — hs_master_8_digit rebuilt successfully.")
    except Exception as e:
        conn.rollback()
        print(f"\n❌ DB error: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
