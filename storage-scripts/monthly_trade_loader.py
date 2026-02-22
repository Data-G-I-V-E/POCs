"""
Monthly Trade Data Loader

Reads DGFT TradeStat monthly Excel files from data/trade_data/dgft_tradestat/2024/
and loads them into the monthly_export_statistics PostgreSQL table.

File naming: {hs_code}-{country}.xlsx  (e.g., 070310-aus.xlsx)
Folder structure: 2024/{Month}/*.xlsx

Usage:
    python storage-scripts/monthly_trade_loader.py
"""

import os
import re
import sys
import pandas as pd
import psycopg2
from pathlib import Path
from datetime import datetime

# Add parent dir so we can import config
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config

# =====================================================
# CONSTANTS
# =====================================================

# Map filename country abbreviation → database country_code
COUNTRY_FILE_TO_DB = {
    'aus': 'AUS',
    'uae': 'UAE',
    'uk': 'GBR',
}

# Month name → month number
MONTH_NUM = {
    'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4,
    'May': 5, 'Jun': 6, 'Jul': 7, 'Aug': 8,
    'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
}

DATA_DIR = Config.ROOT_DIR / "data" / "trade_data" / "dgft_tradestat" / "2024"

# =====================================================
# TABLE CREATION
# =====================================================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS monthly_export_statistics (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10) NOT NULL,
    country_code VARCHAR(10) NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    month_name VARCHAR(3) NOT NULL,

    -- Monthly values (₹ Crore)
    export_value_crore DECIMAL(15,2),
    prev_year_value_crore DECIMAL(15,2),
    monthly_growth_pct DECIMAL(10,2),

    -- Year-to-date cumulative
    ytd_value_crore DECIMAL(15,2),
    prev_ytd_value_crore DECIMAL(15,2),
    ytd_growth_pct DECIMAL(10,2),

    -- Total line (all countries/commodities combined)
    total_monthly_value_crore DECIMAL(15,2),
    total_ytd_value_crore DECIMAL(15,2),

    -- Metadata
    source_file VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(hs_code, country_code, year, month)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_monthly_hs ON monthly_export_statistics(hs_code);
CREATE INDEX IF NOT EXISTS idx_monthly_country ON monthly_export_statistics(country_code);
CREATE INDEX IF NOT EXISTS idx_monthly_year_month ON monthly_export_statistics(year, month);
CREATE INDEX IF NOT EXISTS idx_monthly_composite ON monthly_export_statistics(hs_code, country_code, year, month);
CREATE INDEX IF NOT EXISTS idx_monthly_chapter ON monthly_export_statistics((LEFT(hs_code, 2)));
"""

# =====================================================
# VIEW CREATION (for SQL Agent convenience)
# =====================================================

CREATE_VIEW_SQL = """
-- Monthly export data with country names and HS descriptions
CREATE OR REPLACE VIEW v_monthly_exports AS
SELECT
    m.id,
    m.hs_code,
    LEFT(m.hs_code, 2) AS chapter,
    h.description AS hs_description,
    m.country_code,
    c.country_name,
    m.year,
    m.month,
    m.month_name,
    m.export_value_crore,
    m.prev_year_value_crore,
    m.monthly_growth_pct,
    m.ytd_value_crore,
    m.prev_ytd_value_crore,
    m.ytd_growth_pct,
    m.total_monthly_value_crore,
    m.total_ytd_value_crore
FROM monthly_export_statistics m
LEFT JOIN countries c ON m.country_code = c.country_code
LEFT JOIN hs_codes h ON m.hs_code = h.hs_code;

-- Quarterly aggregation view
CREATE OR REPLACE VIEW v_quarterly_exports AS
SELECT
    hs_code,
    country_code,
    year,
    CASE
        WHEN month BETWEEN 1 AND 3 THEN 'Q1'
        WHEN month BETWEEN 4 AND 6 THEN 'Q2'
        WHEN month BETWEEN 7 AND 9 THEN 'Q3'
        WHEN month BETWEEN 10 AND 12 THEN 'Q4'
    END AS quarter,
    CASE
        WHEN month BETWEEN 1 AND 3 THEN 1
        WHEN month BETWEEN 4 AND 6 THEN 2
        WHEN month BETWEEN 7 AND 9 THEN 3
        WHEN month BETWEEN 10 AND 12 THEN 4
    END AS quarter_num,
    SUM(export_value_crore) AS quarterly_export_crore,
    SUM(prev_year_value_crore) AS prev_quarterly_export_crore,
    ROUND(
        CASE
            WHEN SUM(prev_year_value_crore) > 0
            THEN ((SUM(export_value_crore) - SUM(prev_year_value_crore)) / SUM(prev_year_value_crore)) * 100
            ELSE NULL
        END, 2
    ) AS quarterly_growth_pct,
    COUNT(*) AS months_in_quarter
FROM monthly_export_statistics
GROUP BY hs_code, country_code, year,
    CASE WHEN month BETWEEN 1 AND 3 THEN 'Q1'
         WHEN month BETWEEN 4 AND 6 THEN 'Q2'
         WHEN month BETWEEN 7 AND 9 THEN 'Q3'
         WHEN month BETWEEN 10 AND 12 THEN 'Q4' END,
    CASE WHEN month BETWEEN 1 AND 3 THEN 1
         WHEN month BETWEEN 4 AND 6 THEN 2
         WHEN month BETWEEN 7 AND 9 THEN 3
         WHEN month BETWEEN 10 AND 12 THEN 4 END;
"""


def safe_float(val):
    """Convert a value to float, handling '-', NaN, empty strings."""
    if val is None:
        return None
    s = str(val).strip()
    if s in ('', '-', 'nan', 'NaN', 'None'):
        return None
    try:
        return float(s.replace(',', ''))
    except (ValueError, TypeError):
        return None


def parse_file(filepath, hs_code, country_code, month_name, year=2024):
    """
    Parse one DGFT TradeStat Excel file and return a dict of extracted values.

    Two formats exist:
      - Commoditywise (aus, uae): cols = [S.No, Country, M-2023(R), M-2024(R), %Gr, YTD2023(R), YTD2024(R), %Gr]
      - Countrywise (uk):         cols = [S.No, HSCode, Commodity, M-2023(R), M-2024(R), %Gr, YTD2023(R), YTD2024(R), %Gr]
    """
    try:
        df = pd.read_excel(filepath, header=None)
    except Exception as e:
        print(f"  ⚠️  Could not read {filepath}: {e}")
        return None

    if df.shape[0] < 4:
        print(f"  ⚠️  Too few rows in {filepath}: {df.shape}")
        return None

    # Detect format by checking header row (row index 2)
    header_row = df.iloc[2].tolist()
    header_str = ' '.join(str(x) for x in header_row if pd.notna(x)).upper()

    is_countrywise = 'HSCODE' in header_str.replace(' ', '') or 'COMMODITY' in header_str.upper()

    # Data row is row index 3 (the specific HS/country row)
    data_row = df.iloc[3].tolist()
    # Total row is row index 4
    total_row = df.iloc[4].tolist() if df.shape[0] > 4 else [None] * len(data_row)

    if is_countrywise:
        # UK format: S.No, HSCode, Commodity, M-2023(R), M-2024(R), %Gr, YTD-2023(R), YTD-2024(R), %Gr
        prev_year_val = safe_float(data_row[3])
        curr_year_val = safe_float(data_row[4])
        monthly_growth = safe_float(data_row[5])
        prev_ytd_val = safe_float(data_row[6])
        curr_ytd_val = safe_float(data_row[7])
        ytd_growth = safe_float(data_row[8]) if len(data_row) > 8 else None

        total_monthly = safe_float(total_row[4]) if len(total_row) > 4 else None
        total_ytd = safe_float(total_row[7]) if len(total_row) > 7 else None
    else:
        # AUS/UAE format: S.No, Country, M-2023(R), M-2024(R), %Gr, YTD2023(R), YTD2024(R), %Gr
        prev_year_val = safe_float(data_row[2])
        curr_year_val = safe_float(data_row[3])
        monthly_growth = safe_float(data_row[4])
        prev_ytd_val = safe_float(data_row[5])
        curr_ytd_val = safe_float(data_row[6])
        ytd_growth = safe_float(data_row[7]) if len(data_row) > 7 else None

        total_monthly = safe_float(total_row[3]) if len(total_row) > 3 else None
        total_ytd = safe_float(total_row[6]) if len(total_row) > 6 else None

    return {
        'hs_code': hs_code,
        'country_code': country_code,
        'year': year,
        'month': MONTH_NUM[month_name],
        'month_name': month_name,
        'export_value_crore': curr_year_val,
        'prev_year_value_crore': prev_year_val,
        'monthly_growth_pct': monthly_growth,
        'ytd_value_crore': curr_ytd_val,
        'prev_ytd_value_crore': prev_ytd_val,
        'ytd_growth_pct': ytd_growth,
        'total_monthly_value_crore': total_monthly,
        'total_ytd_value_crore': total_ytd,
        'source_file': str(Path(filepath).relative_to(Config.ROOT_DIR)),
    }


def main():
    print("=" * 70)
    print("MONTHLY TRADE DATA LOADER")
    print("=" * 70)
    print(f"Source: {DATA_DIR}")
    print(f"Year: 2024")
    print()

    if not DATA_DIR.exists():
        print(f"❌ Data directory not found: {DATA_DIR}")
        return

    # Connect to database
    conn = psycopg2.connect(**Config.DB_CONFIG)
    cur = conn.cursor()

    # Create table and views
    print("Creating table monthly_export_statistics...")
    cur.execute(CREATE_TABLE_SQL)
    conn.commit()
    print("✓ Table created")

    print("Creating views...")
    cur.execute(CREATE_VIEW_SQL)
    conn.commit()
    print("✓ Views created (v_monthly_exports, v_quarterly_exports)")
    print()

    # Process each month
    stats = {
        'total_files': 0,
        'loaded': 0,
        'skipped': 0,
        'errors': 0,
        'months_processed': set(),
        'hs_codes': set(),
        'countries': set(),
    }

    for month_name in sorted(os.listdir(DATA_DIR)):
        month_path = DATA_DIR / month_name
        if not month_path.is_dir() or month_name not in MONTH_NUM:
            continue

        print(f"📅 Processing {month_name} 2024...")
        month_count = 0

        for filename in sorted(os.listdir(month_path)):
            if not filename.endswith('.xlsx'):
                continue

            stats['total_files'] += 1

            # Parse filename: hs_code-country.xlsx
            base = filename.replace('.xlsx', '')
            parts = base.split('-')
            if len(parts) != 2:
                print(f"  ⚠️  Unexpected filename format: {filename}")
                stats['skipped'] += 1
                continue

            hs_code = parts[0]
            country_abbr = parts[1]

            if country_abbr not in COUNTRY_FILE_TO_DB:
                # Skip unknown country files (e.g., 'emts' if any)
                stats['skipped'] += 1
                continue

            country_code = COUNTRY_FILE_TO_DB[country_abbr]

            # Parse the Excel file
            filepath = month_path / filename
            record = parse_file(filepath, hs_code, country_code, month_name)

            if record is None:
                stats['errors'] += 1
                continue

            # Upsert into database
            try:
                cur.execute("""
                    INSERT INTO monthly_export_statistics
                        (hs_code, country_code, year, month, month_name,
                         export_value_crore, prev_year_value_crore, monthly_growth_pct,
                         ytd_value_crore, prev_ytd_value_crore, ytd_growth_pct,
                         total_monthly_value_crore, total_ytd_value_crore,
                         source_file)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (hs_code, country_code, year, month)
                    DO UPDATE SET
                        export_value_crore = EXCLUDED.export_value_crore,
                        prev_year_value_crore = EXCLUDED.prev_year_value_crore,
                        monthly_growth_pct = EXCLUDED.monthly_growth_pct,
                        ytd_value_crore = EXCLUDED.ytd_value_crore,
                        prev_ytd_value_crore = EXCLUDED.prev_ytd_value_crore,
                        ytd_growth_pct = EXCLUDED.ytd_growth_pct,
                        total_monthly_value_crore = EXCLUDED.total_monthly_value_crore,
                        total_ytd_value_crore = EXCLUDED.total_ytd_value_crore,
                        source_file = EXCLUDED.source_file
                """, (
                    record['hs_code'], record['country_code'],
                    record['year'], record['month'], record['month_name'],
                    record['export_value_crore'], record['prev_year_value_crore'],
                    record['monthly_growth_pct'],
                    record['ytd_value_crore'], record['prev_ytd_value_crore'],
                    record['ytd_growth_pct'],
                    record['total_monthly_value_crore'], record['total_ytd_value_crore'],
                    record['source_file'],
                ))
                stats['loaded'] += 1
                stats['hs_codes'].add(hs_code)
                stats['countries'].add(country_code)
                month_count += 1
            except Exception as e:
                print(f"  ❌ Error inserting {filename}: {e}")
                stats['errors'] += 1
                conn.rollback()
                continue

        conn.commit()
        stats['months_processed'].add(month_name)
        print(f"  ✓ {month_count} records loaded")

    print()
    print("=" * 70)
    print("LOADING COMPLETE")
    print("=" * 70)
    print(f"Files found:       {stats['total_files']}")
    print(f"Records loaded:    {stats['loaded']}")
    print(f"Files skipped:     {stats['skipped']}")
    print(f"Errors:            {stats['errors']}")
    print(f"Months processed:  {len(stats['months_processed'])}")
    print(f"HS codes:          {len(stats['hs_codes'])} ({', '.join(sorted(stats['hs_codes']))})")
    print(f"Countries:         {', '.join(sorted(stats['countries']))}")
    print()

    # Verify
    cur.execute("SELECT COUNT(*) FROM monthly_export_statistics")
    print(f"Total rows in monthly_export_statistics: {cur.fetchone()[0]}")

    cur.execute("""
        SELECT hs_code, country_code, month_name, export_value_crore, ytd_value_crore
        FROM monthly_export_statistics
        ORDER BY hs_code, country_code, month
        LIMIT 5
    """)
    print("\nSample data:")
    for row in cur.fetchall():
        print(f"  {row[0]} → {row[1]} | {row[2]}: ₹{row[3]} Cr (YTD: ₹{row[4]} Cr)")

    cur.execute("""
        SELECT country_code, COUNT(*), SUM(export_value_crore)
        FROM monthly_export_statistics
        GROUP BY country_code
        ORDER BY country_code
    """)
    print("\nBy country:")
    for row in cur.fetchall():
        val = f"₹{row[2]:.2f} Cr" if row[2] else "N/A"
        print(f"  {row[0]}: {row[1]} records, total {val}")

    conn.close()
    print("\n✓ Done!")


if __name__ == "__main__":
    main()
