# Data Storage Architecture

Complete documentation of how all trade data is stored, organized, and connected in the system.

---

## 📊 Overview

### Storage Types
1. **PostgreSQL Database** - Structured data (HS codes, policies, trade statistics)
2. **FAISS + ChromaDB** - Trade agreements (article-aware chunking with cross-reference resolution)
3. **ChromaDB** - DGFT policy vector embeddings for semantic search

---

## 🗄️ PostgreSQL Database Structure

### Database Name: `PPL-AI`
**Location**: localhost:5432  
**Schema**: public

---

## 1️⃣ ITC HS Notifications & Product Data

### Table: `itc_hs_products`
**Purpose**: Complete ITC HS nomenclature with export policies  
**Rows**: ~5,000+ products

**Schema**:
```sql
CREATE TABLE itc_hs_products (
    id SERIAL PRIMARY KEY,
    chapter_code VARCHAR(2),
    hs_code VARCHAR(10) UNIQUE,
    description TEXT,
    export_policy VARCHAR(100),      -- 'Free', 'Restricted', 'Prohibited', 'STE'
    notification_no VARCHAR(50),     -- ITC notification reference
    notification_date DATE,
    parent_hs_code VARCHAR(10),      -- Hierarchical relationship
    level INTEGER,                   -- Code depth (2/4/6/8 digit)
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**How Stored**:
- **Hierarchical Structure**: `parent_hs_code` links child codes to parents
  - Chapter (2-digit) → Heading (4-digit) → Subheading (6-digit) → Tariff item (8-digit)
  - Example: `07` → `0713` → `071310` → `07131010`
- **Notification Tracking**: Each code references ITC notification that governs it
- **Export Policy**: Direct storage of policy status

**Loaded By**: `storage-scripts/itc_data_loader.py`

---

### Table: `itc_chapters`
**Purpose**: Chapter-level information  
**Rows**: 97 chapters (Chapter 01-97)

**Schema**:
```sql
CREATE TABLE itc_chapters (
    id SERIAL PRIMARY KEY,
    chapter_code VARCHAR(2) UNIQUE,
    chapter_name TEXT,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

**Connection**: `itc_hs_products.chapter_code` → `itc_chapters.chapter_code`

---

### Table: `itc_chapter_notes`
**Purpose**: Chapter notes, policy conditions, export licensing requirements  
**Rows**: 446 notes

**Schema**:
```sql
CREATE TABLE itc_chapter_notes (
    id SERIAL PRIMARY KEY,
    chapter_code VARCHAR(2),
    note_type VARCHAR(50),           -- 'main_note', 'policy_condition', 'export_licensing'
    sl_no INTEGER,                   -- Serial number within type
    note_text TEXT,
    notification_no VARCHAR(50),
    notification_date DATE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (chapter_code) REFERENCES itc_chapters(chapter_code)
);
```

**How Stored**:
- **Type Classification**: Notes categorized by purpose
  - `main_note`: General chapter notes
  - `policy_condition`: Policy conditions (e.g., "Policy Condition 1")
  - `export_licensing`: Licensing requirements
- **Sequential Ordering**: `sl_no` maintains order within each type

**Loaded By**: `storage-scripts/itc_data_loader.py`

---

## 2️⃣ Policy References & Connections (Chapter ↔ Article)

### Table: `itc_hs_policy_references`
**Purpose**: Links HS codes to chapter policy conditions  
**Rows**: 57 codes with policy references

**Schema**:
```sql
CREATE TABLE itc_hs_policy_references (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10),
    policy_reference TEXT,           -- 'Policy Condition 1', 'Export Licensing Note 2', etc.
    chapter_code VARCHAR(2),
    notification_no VARCHAR(50),
    notification_date DATE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    FOREIGN KEY (hs_code) REFERENCES itc_hs_products(hs_code),
    FOREIGN KEY (chapter_code) REFERENCES itc_chapters(chapter_code)
);
```

**How Connections Work**:
```
HS Code → policy_reference → Chapter Policy Definition
07131010 → "Policy Condition 1" → (Chapter 07, Policy Condition 1) → Full policy text
```

**Example**:
```sql
-- HS Code 07131010 (Yellow Peas)
hs_code: '07131010'
policy_reference: 'Policy Condition 1'
chapter_code: '07'

-- This links to:
itc_chapter_policies WHERE chapter_code='07' AND policy_type='Policy Condition 1'
```

**Loaded By**: `storage-scripts/itc_data_loader.py`

---

### Table: `itc_chapter_policies`
**Purpose**: Full text of chapter-level policy conditions  
**Rows**: 385 policy definitions

**Schema**:
```sql
CREATE TABLE itc_chapter_policies (
    id SERIAL PRIMARY KEY,
    chapter_code VARCHAR(2),
    policy_type VARCHAR(100),        -- 'Policy Condition 1', 'Policy Condition 2', etc.
    policy_text TEXT,                -- Full policy requirement text
    notification_no VARCHAR(50),
    notification_date DATE,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(chapter_code, policy_type),
    FOREIGN KEY (chapter_code) REFERENCES itc_chapters(chapter_code)
);
```

**How Stored**:
- **Unique Policy per Chapter**: Each chapter can have multiple policy types
- **Text Storage**: Full policy text in `policy_text` column (no JSON needed)
- **Cross-Reference**: Used by `itc_hs_policy_references` to get full policy text

**Example Data**:
```sql
chapter_code: '07'
policy_type: 'Policy Condition 1'
policy_text: 'Export shall be through Custom EDI ports. However, export through 
              non-EDI Land Custom Stations (LCS) on Indo-Bangladesh and Indo-Nepal 
              border shall also be allowed subject to registration of quantity with DGFT.'
```

**Loaded By**: `storage-scripts/itc_data_loader.py`

---

## 3️⃣ Restricted Items

### Table: `restricted_items`
**Purpose**: HS codes with export restrictions  
**Rows**: Variable (depends on current restrictions)

**Schema**:
```sql
CREATE TABLE restricted_items (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10) UNIQUE,
    description TEXT,
    export_policy VARCHAR(50),       -- Usually 'Restricted'
    policy_condition TEXT,           -- Specific restriction details
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**How Stored**:
- **Direct Storage**: Each restricted HS code stored separately
- **Policy Details**: `policy_condition` contains specific restrictions
- **No JSON**: Uses TEXT columns for policy details

**Example Data**:
```sql
hs_code: '10011100'
description: 'Durum wheat seed'
export_policy: 'Restricted'
policy_condition: 'Export allowed only against specific authorization'
```

**Loaded By**: `storage-scripts/restrictions.py`

---

## 4️⃣ Prohibited Items

### Table: `prohibited_items`
**Purpose**: HS codes with complete export prohibition  
**Rows**: Variable (depends on current prohibitions)

**Schema**:
```sql
CREATE TABLE prohibited_items (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10) UNIQUE,
    description TEXT,
    export_policy VARCHAR(50),       -- 'Prohibited'
    policy_condition TEXT,           -- Reason for prohibition
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**How Stored**:
- **Similar to restricted_items**: Same structure
- **Policy Condition**: Explains why item is prohibited

**Example Data**:
```sql
hs_code: '05119110'
description: 'Wild animals covered under Wildlife Protection Act'
export_policy: 'Prohibited'
policy_condition: 'Export of wild animals prohibited under Wildlife Act 1972'
```

**Loaded By**: `storage-scripts/restrictions.py`

---

## 5️⃣ STE Items (State Trading Enterprise)

### Table: `ste_items`
**Purpose**: Items requiring export through designated STEs  
**Rows**: Variable

**Schema**:
```sql
CREATE TABLE ste_items (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10) UNIQUE,
    description TEXT,
    export_policy VARCHAR(50),       -- 'STE'
    policy_condition TEXT,           -- STE requirements
    authorized_entity VARCHAR(200),  -- Which STE can export
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**How Stored**:
- **Entity Specification**: `authorized_entity` column specifies which STE
- **Policy Details**: Stored in text columns

**Example Data**:
```sql
hs_code: '90261010'
description: 'Parts of radiation measuring instruments'
export_policy: 'STE'
authorized_entity: 'Designated State Trading Enterprise'
policy_condition: 'Export only through authorized STE'
```

**Loaded By**: `storage-scripts/ste_items.py`

---

## 6️⃣ Trade Statistics — Annual (Export Values)

### Table: `export_statistics`
**Purpose**: Historical annual export data by HS code, country, and financial year  
**Rows**: 100,000+ records

**Schema**:
```sql
CREATE TABLE export_statistics (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10),
    country_code VARCHAR(10),        -- 'AUS', 'UAE', 'GBR', etc.
    year_label VARCHAR(20),          -- '2023-2024', '2024-2025'
    export_value_crore DECIMAL(15,2),-- Export value in ₹ Crore
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (hs_code) REFERENCES hs_codes(hs_code),
    FOREIGN KEY (country_code) REFERENCES countries(country_code)
);
```

**How Stored**:
- **Time Series**: Year-wise data stored in rows (not JSON)
- **Country-wise**: Separate row per country-year combination
- **Numeric Values**: Decimal type for accurate financial data

**Example Data**:
```sql
hs_code: '070310'
country_code: 'AUS'
year_label: '2023-2024'
export_value_crore: 0.91

hs_code: '070310'
country_code: 'UAE'
year_label: '2023-2024'
export_value_crore: 15.23
```

**Loaded By**: `storage-scripts/export_data.py`

---

### Table: `countries`
**Purpose**: Country reference data  
**Rows**: 3+ countries (expandable)

**Schema**:
```sql
CREATE TABLE countries (
    id SERIAL PRIMARY KEY,
    country_code VARCHAR(10) UNIQUE, -- 'AUS', 'UAE', 'UK'
    country_name VARCHAR(100),       -- 'Australia', 'United Arab Emirates'
    region VARCHAR(100),             -- 'Oceania', 'Middle East', 'Europe'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Connection**: `export_statistics.country_code` → `countries.country_code`

---

### Table: `financial_years`
**Purpose**: Financial year definitions  
**Rows**: Multiple years

**Schema**:
```sql
CREATE TABLE financial_years (
    id SERIAL PRIMARY KEY,
    year_label VARCHAR(20) UNIQUE,   -- '2023-2024'
    start_date DATE,                 -- 2023-04-01
    end_date DATE,                   -- 2024-03-31
    is_current BOOLEAN DEFAULT FALSE
);
```

---

## 6️b️ Monthly Trade Statistics (2024)

### Table: `monthly_export_statistics`
**Purpose**: Month-by-month export data for 2024 across 16 HS codes and 3 countries  
**Rows**: 565 records (16 HS codes × 3 countries × 12 months, minus a few gaps)  
**Created By**: `storage-scripts/monthly_trade_loader.py`

**Source Data**:
```
data/trade_data/dgft_tradestat/2024/
├── Jan/          (47 files)
├── Feb/          (47 files)
├── Mar/          (46 files)
└── ...           (12 months total, 567 xlsx files)

File naming: {hs_code}-{country}.xlsx
Examples: 070310-aus.xlsx, 610910-uae.xlsx, 851762-uk.xlsx
```

**Country mapping**: `aus` → `AUS`, `uae` → `UAE`, `uk` → `GBR`

**Schema**:
```sql
CREATE TABLE monthly_export_statistics (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10) NOT NULL,
    country_code VARCHAR(10) NOT NULL,
    year INTEGER NOT NULL,               -- 2024
    month INTEGER NOT NULL,              -- 1–12
    month_name VARCHAR(3) NOT NULL,      -- 'Jan', 'Feb', etc.

    -- Monthly values (₹ Crore)
    export_value_crore DECIMAL(15,2),          -- Current month 2024
    prev_year_value_crore DECIMAL(15,2),       -- Same month 2023
    monthly_growth_pct DECIMAL(10,2),          -- Month-over-month YoY %

    -- Year-to-date cumulative
    ytd_value_crore DECIMAL(15,2),             -- Jan–{Month} 2024
    prev_ytd_value_crore DECIMAL(15,2),        -- Jan–{Month} 2023
    ytd_growth_pct DECIMAL(10,2),              -- YTD growth %

    -- Total line (all countries/commodities combined)
    total_monthly_value_crore DECIMAL(15,2),
    total_ytd_value_crore DECIMAL(15,2),

    source_file VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(hs_code, country_code, year, month)
);
```

**Indexes**:
- `idx_monthly_hs` — on `hs_code`
- `idx_monthly_country` — on `country_code`
- `idx_monthly_year_month` — on `(year, month)`
- `idx_monthly_composite` — on `(hs_code, country_code, year, month)`
- `idx_monthly_chapter` — on `LEFT(hs_code, 2)` (expression index)

**How Stored**:
- Each Excel file has 2 data rows: specific country/HS row + total row
- Two formats: **Commoditywise** (AUS/UAE files) and **Countrywise** (UK files)
- The loader auto-detects format and extracts the same fields from both
- Values in **₹ Crore** as reported by DGFT TradeStat

**Example Data**:
```
hs_code: '610910'  |  country_code: 'UAE'  |  month: 1 (Jan)
export_value_crore: 143.41  |  prev_year_value_crore: 160.16
monthly_growth_pct: -10.46  |  ytd_value_crore: 143.41
```

---

### View: `v_monthly_exports`
**Purpose**: Monthly exports enriched with country names and HS descriptions  
**Type**: PostgreSQL VIEW

```sql
CREATE VIEW v_monthly_exports AS
SELECT
    m.*, LEFT(m.hs_code, 2) AS chapter,
    h.description AS hs_description,
    c.country_name
FROM monthly_export_statistics m
LEFT JOIN countries c ON m.country_code = c.country_code
LEFT JOIN hs_codes h ON m.hs_code = h.hs_code;
```

**Note**: `chapter` is TEXT (e.g., `'85'`), always compare as string.

---

### View: `v_quarterly_exports`
**Purpose**: Quarterly aggregations from monthly data  
**Type**: PostgreSQL VIEW

```sql
CREATE VIEW v_quarterly_exports AS
SELECT
    hs_code, country_code, year,
    quarter (Q1–Q4), quarter_num (1–4),
    SUM(export_value_crore) AS quarterly_export_crore,
    SUM(prev_year_value_crore) AS prev_quarterly_export_crore,
    quarterly_growth_pct
FROM monthly_export_statistics
GROUP BY hs_code, country_code, year, quarter;
```

**Sample query**: Best month for electronics to Australia
```sql
SELECT month_name, SUM(export_value_crore) AS total
FROM v_monthly_exports
WHERE chapter = '85' AND country_code = 'AUS'
GROUP BY month_name, month ORDER BY total DESC LIMIT 1;
-- Result: Nov, ₹108.60 Cr
```

---

## 7️⃣ HS Codes Base Table

### Table: `hs_codes`
**Purpose**: Master HS code reference (primarily 6-digit codes)  
**Rows**: 5,000+ codes

**Schema**:
```sql
CREATE TABLE hs_codes (
    id SERIAL PRIMARY KEY,
    hs_code VARCHAR(10) UNIQUE,
    description TEXT,
    code_level INTEGER,              -- 2, 4, 6, or 8 digit
    chapter_number VARCHAR(10),
    parent_code VARCHAR(10),         -- Hierarchical link
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**How Stored**:
- **Hierarchy via parent_code**: No JSON, uses relational links
- **Level Tracking**: `code_level` indicates depth in hierarchy

**Loaded By**: `storage-scripts/run_schema.py`

---

### Table: `chapters`
**Purpose**: HS chapter master reference  
**Rows**: 97 chapters

**Schema**:
```sql
CREATE TABLE chapters (
    id SERIAL PRIMARY KEY,
    chapter_number VARCHAR(10) UNIQUE,
    title TEXT,
    notes TEXT,                      -- Chapter notes stored as text
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Connection**: `hs_codes.chapter_number` → `chapters.chapter_number`

---

## 8️⃣ Unified Views (Integration Layer)

### View: `v_export_policy_unified`
**Purpose**: Single view combining ALL policy information  
**Type**: PostgreSQL VIEW

**What It Combines**:
```sql
CREATE VIEW v_export_policy_unified AS
SELECT 
    -- HS Code Info (from hs_codes + itc_hs_products)
    hs_code, hs_description, chapter_number, code_level,
    
    -- ITC Policy
    itc_policy, itc_notification, itc_date,
    
    -- Policy References (CONNECTIONS!)
    policy_reference,           -- e.g., "Policy Condition 1"
    policy_reference_text,      -- Full text from itc_chapter_policies
    
    -- Prohibited Status
    is_prohibited, prohibited_policy, prohibited_condition,
    
    -- Restricted Status
    is_restricted, restricted_policy, restricted_condition,
    
    -- STE Status
    is_ste, ste_policy, ste_entity,
    
    -- Overall Status
    overall_status              -- 'FREE', 'PROHIBITED', 'RESTRICTED', 'STE_ONLY', 'CONDITIONAL'
FROM (all_codes) ac
LEFT JOIN itc_hs_products itc ON ac.hs_code = itc.hs_code
LEFT JOIN itc_hs_policy_references pr ON ac.hs_code = pr.hs_code
LEFT JOIN itc_chapter_policies cp ON pr.chapter_code = cp.chapter_code 
    AND pr.policy_reference = cp.policy_type
LEFT JOIN prohibited_items pi ON ac.hs_code = pi.hs_code
LEFT JOIN restricted_items ri ON ac.hs_code = ri.hs_code
LEFT JOIN ste_items ste ON ac.hs_code = ste.hs_code;
```

**Key Feature - Policy References Connection**:
```
itc_hs_policy_references.policy_reference 
    ↓ (JOIN on chapter_code + policy_type)
itc_chapter_policies.policy_text
```

**How Agents Query**:
```sql
-- Get HS code with all policy info including references
SELECT * FROM v_export_policy_unified WHERE hs_code = '07131010';
```

**Created By**: `storage-scripts/database_unification.py`

---

### View: `v_hs_codes_complete`
**Purpose**: Complete HS code info with policies  
**Type**: PostgreSQL VIEW

```sql
CREATE VIEW v_hs_codes_complete AS
SELECT 
    hc.*,
    ch.title AS chapter_title,
    ch.notes AS chapter_notes,
    ep.overall_status,
    ep.is_prohibited,
    ep.is_restricted,
    ep.is_ste
FROM hs_codes hc
LEFT JOIN chapters ch ON hc.chapter_number = ch.chapter_number
LEFT JOIN v_export_policy_unified ep ON hc.hs_code = ep.hs_code;
```

---

### Materialized View: `mv_hs_export_summary`
**Purpose**: Pre-computed export statistics aggregations  
**Type**: PostgreSQL MATERIALIZED VIEW

```sql
CREATE MATERIALIZED VIEW mv_hs_export_summary AS
SELECT 
    es.hs_code,
    hc.description,
    COUNT(DISTINCT es.country_code) AS export_countries_count,
    SUM(es.export_value_crore) AS total_export_value_crore,
    MAX(es.year_label) AS latest_year,
    array_agg(DISTINCT es.country_code) AS export_countries  -- Array, not JSON
FROM export_statistics es
JOIN hs_codes hc ON es.hs_code = hc.hs_code
GROUP BY es.hs_code, hc.description;
```

**Refresh**: `REFRESH MATERIALIZED VIEW mv_hs_export_summary;`

---

## 9️⃣ Trade Agreements (FAISS + ChromaDB)

### Storage: `agreements_rag_store/`
**Status**: ✅ Operational  
**Created By**: `storage-scripts/agreements_ingest_enhanced.py`  
**Searched By**: `storage-scripts/agreements_retriever.py` → `AgreementsAgent` in `agents/agreements_agent.py`

### Source Data
```
data/agreements/
├── australia/     (34 PDFs - AI-ECTA chapters, annexes, schedules)
├── uae/           (39 PDFs - India-UAE CEPA chapters and annexes)
└── uk/            (68 PDFs - India-UK CETA chapters, schedules, annexes)
```

**Total**: 141 PDFs → 108 processed, 21 skipped (tariff schedules), 12 empty/OCR-only

### How Ingestion Works

#### Step 1: PDF Loading & Smart Skipping
```python
# Files matching these patterns are SKIPPED (tariff data is already in PostgreSQL)
SKIP_PATTERNS = [
    "tariff", "schedule", "annex-1", "annex-2a", "annex-2b",
    "appendix-2a", "appendix_2a"
]
```

#### Step 2: OCR Cleanup
The UAE PDFs were scanned/OCR'd with frequent errors. The ingestion script fixes 15+ patterns:
```python
OCR_FIXES = {
    "Articlc": "Article",
    "thc ": "the ",
    "Partics": "Parties",
    "mcasures": "measures",
    "cxport": "export",
    # ... 10+ more patterns
}
```

#### Step 3: Article-Aware Chunking
Instead of blind fixed-size chunking, the system splits on `Article X.Y` boundaries:

```python
# Regex pattern used for splitting
pattern = r'(?=(?:ARTICLE|Article)\s+\d+(?:\.\d+)?)'

# Each chunk gets metadata:
{
    "text": "Article 4.3\nGoods Not Wholly Produced or Obtained...",
    "metadata": {
        "country": "australia",
        "filename": "04-Rules-of-Origin.pdf",
        "agreement": "India-Australia ECTA (AI-ECTA)",
        "doc_type": "chapter",           # chapter | annex | schedule | appendix
        "chapter_num": "04",
        "article_num": "4.3",
        "article_full": "Article 4.3",
        "chunk_id": "aus_04_rules_of_origin_art4.3_0",
        "cross_ref_articles": "4.4, 4.6",  # Auto-extracted
        "cross_ref_annexes": "3-A",        # Auto-extracted
        "has_cross_refs": true
    }
}
```

#### Step 4: Cross-Reference Extraction
When an article mentions other articles, the system extracts those references:

```python
# Patterns matched:
"Article 4.6"        → cross_ref_articles: ["4.6"]
"Articles 3.1-3.5"   → cross_ref_articles: ["3.1", "3.5"]
"Annex 3-A"          → cross_ref_annexes: ["3-A"]
"paragraph 2(b)"     → cross_ref_articles: ["2"]
```

- **48% of all chunks** (1,201 out of 2,524) have cross-references
- At search time, the `AgreementsRetriever` automatically fetches referenced articles

### Storage Structure

```
agreements_rag_store/
├── agreements.index           # FAISS FlatIP index (cosine similarity via normalized vectors)
├── documents.json             # All chunk text + metadata (2,524 entries)
├── article_index.json         # Article → chunk position mapping (885 articles)
├── chunk_id_mapping.json      # chunk_id → FAISS position mapping
├── ingestion_stats.json       # Ingestion run statistics
└── agreements_chroma/         # ChromaDB persistent collection
    └── trade_agreements         # Collection name
```

#### FAISS Index (`agreements.index`)
```python
# Inner-product index with normalized vectors = cosine similarity
index = faiss.IndexFlatIP(384)  # 384-dim from all-MiniLM-L6-v2

# Search:
query_vector = model.encode([query])   # Normalize
faiss.normalize_L2(query_vector)
scores, indices = index.search(query_vector, top_k=5)
# scores are cosine similarities in [0, 1]
```

#### ChromaDB Collection (`trade_agreements`)
```python
{
    "documents": ["Article 4.3 text..."],
    "embeddings": [vector_384d],
    "metadatas": [{
        "country": "australia",
        "filename": "04-Rules-of-Origin.pdf",
        "agreement": "India-Australia ECTA (AI-ECTA)",
        "doc_type": "chapter",
        "chapter_num": "04",
        "article_num": "4.3",
        "article_full": "Article 4.3",
        "cross_ref_articles": "4.4, 4.6",
        "cross_ref_annexes": "3-A",
        "has_cross_refs": "true"
    }],
    "ids": ["aus_04_rules_of_origin_art4.3_0"]
}
```

ChromaDB is used for **metadata-filtered searches** (e.g., "search only Australia documents"), while FAISS handles **pure vector similarity** searches.

#### Article Index (`article_index.json`)
```python
# Maps article identifiers to their FAISS positions
{
    "australia_4.3": [42],                  # Single chunk
    "australia_4.6": [45, 46],              # Multi-chunk article
    "uae_3.1": [890],
    "uk_5.12": [1650, 1651, 1652],
    # ... 885 articles total
}

# Used by AgreementsRetriever for cross-reference resolution:
# When Article 4.3 mentions Article 4.6, the retriever
# looks up "australia_4.6" in article_index.json to find
# the FAISS positions, then fetches those chunks automatically.
```

### How Search Works (AgreementsRetriever)

```python
from agreements_retriever import AgreementsRetriever

retriever = AgreementsRetriever(storage_path="agreements_rag_store")

# Basic search
results = retriever.search(
    query="rules of origin for textiles",
    top_k=5,
    country="australia",          # Optional: filter by country
    include_cross_refs=True       # Auto-fetch referenced articles
)

# Results include:
# - Primary matches (from FAISS + ChromaDB)
# - Cross-referenced articles (automatically resolved)
# - Each result has: text, metadata, similarity_score, source type
```

### Ingestion Statistics

| Metric | Value |
|--------|-------|
| PDFs found | 141 |
| PDFs processed | 108 |
| PDFs skipped (tariff tables) | 21 |
| PDFs empty/OCR-only | 12 |
| Total chunks | 2,524 |
| Articles parsed | 888 |
| Articles indexed | 885 |
| Chunks with cross-refs | 1,201 (48%) |
| Embedding model | all-MiniLM-L6-v2 (384-dim) |
| FAISS index type | FlatIP (cosine similarity) |

**Per-Country Breakdown**:

| Country | Agreement | PDFs Processed | Chunks | Articles | Cross-refs |
|---------|-----------|----------------|--------|----------|------------|
| Australia | AI-ECTA | 24 | 577 | 190 | 231 |
| UAE | India-UAE CEPA | 35 | 751 | 249 | 209 |
| UK | India-UK CETA | 49 | 1,196 | 449 | 761 |

**Created By**: `storage-scripts/agreements_ingest_enhanced.py`  
**Loaded By**: `storage-scripts/agreements_retriever.py`  
**Used By**: `AgreementsAgent` in `agents/agreements_agent.py`

---

## 🔟 DGFT Policy Documents

### Storage: ChromaDB
**Location**: `dgft_chroma_db/`  
**Status**: ✅ Operational

**Collection**: `dgft_policies` (or similar)
```python
{
    "documents": ["DGFT policy text chunk"],
    "embeddings": [vector_embedding],
    "metadatas": [{
        "source": "Foreign Trade Policy 2023",
        "chapter": "Chapter 4",
        "page": 15,
        "policy_type": "export_promotion"
    }],
    "ids": ["dgft_ftp_2023_ch4_p15_1"]
}
```

**No SQL Tables**: Pure vector storage, no relational connections needed

---

## 🔗 How Connections Are Maintained

### 1. **Hierarchical Relationships** (HS Codes)
**Method**: Foreign Key in same table
```sql
-- Parent-child via parent_hs_code
hs_code: '07131010'
parent_hs_code: '071310'  ← Links to parent row
```

**Not JSON**: Uses relational structure, traverse via SQL:
```sql
-- Get all children of a code
SELECT * FROM hs_codes WHERE parent_code = '071310';
```

---

### 2. **Policy References** (Chapter ↔ Policy Condition)
**Method**: Two-table join via reference string
```sql
-- Table 1: itc_hs_policy_references
hs_code: '07131010'
policy_reference: 'Policy Condition 1'
chapter_code: '07'

-- Table 2: itc_chapter_policies
chapter_code: '07'
policy_type: 'Policy Condition 1'  ← Matches policy_reference
policy_text: 'Full policy text here...'

-- JOIN Query:
SELECT hp.hs_code, hp.policy_reference, cp.policy_text
FROM itc_hs_policy_references hp
JOIN itc_chapter_policies cp 
  ON hp.chapter_code = cp.chapter_code 
  AND hp.policy_reference = cp.policy_type;
```

**Not JSON**: Pure SQL joins, no JSON columns

---

### 3. **Trade Statistics** (HS Code ↔ Country ↔ Year)
**Method**: Separate row per combination
```sql
-- Multiple rows, not nested JSON
Row 1: hs_code='070310', country='AUS', year='2023-2024', value=0.91
Row 2: hs_code='070310', country='AUS', year='2024-2025', value=1.15
Row 3: hs_code='070310', country='UAE', year='2023-2024', value=15.23
```

**Query Pattern**:
```sql
-- Get all years for a country
SELECT * FROM export_statistics 
WHERE hs_code = '070310' AND country_code = 'AUS' 
ORDER BY year_label;
```

---

### 4. **Multi-table Policies** (Prohibited + Restricted + STE)
**Method**: Separate tables, unified via VIEW
```sql
-- Three separate tables:
prohibited_items (hs_code, description, policy_condition)
restricted_items (hs_code, description, policy_condition)
ste_items (hs_code, description, authorized_entity)

-- Combined via v_export_policy_unified VIEW with LEFT JOINs
-- Single query returns all policy info
```

---

### 5. **Chapter Notes** (Multiple notes per chapter)
**Method**: Multiple rows with type classification
```sql
-- Multiple rows per chapter, classified by note_type
chapter_code: '07', note_type: 'main_note', sl_no: 1, note_text: '...'
chapter_code: '07', note_type: 'main_note', sl_no: 2, note_text: '...'
chapter_code: '07', note_type: 'policy_condition', sl_no: 1, note_text: '...'
chapter_code: '07', note_type: 'export_licensing', sl_no: 1, note_text: '...'
```

**Not JSON Array**: Each note is a row, ordered by `sl_no`

---

## 📋 Summary Table

| Data Type | Storage | Location | Connections | JSON Used? |
|-----------|---------|----------|-------------|------------|
| **ITC HS Products** | PostgreSQL Table | `itc_hs_products` | `parent_hs_code` FK | ❌ No |
| **Policy References** | PostgreSQL Table | `itc_hs_policy_references` | JOIN on chapter + policy_type | ❌ No |
| **Chapter Policies** | PostgreSQL Table | `itc_chapter_policies` | Referenced by policy_reference | ❌ No |
| **Chapter Notes** | PostgreSQL Table | `itc_chapter_notes` | FK to chapters, ordered by sl_no | ❌ No |
| **Restricted Items** | PostgreSQL Table | `restricted_items` | Direct hs_code lookup | ❌ No |
| **Prohibited Items** | PostgreSQL Table | `prohibited_items` | Direct hs_code lookup | ❌ No |
| **STE Items** | PostgreSQL Table | `ste_items` | Direct hs_code lookup | ❌ No |
| **Export Statistics (Annual)** | PostgreSQL Table | `export_statistics` | FK to hs_codes, countries | ❌ No |
| **Export Statistics (Monthly)** | PostgreSQL Table | `monthly_export_statistics` | 16 HS codes × 3 countries × 12 months | ❌ No |
| **Monthly Exports View** | PostgreSQL VIEW | `v_monthly_exports` | Joins hs_codes, countries | ❌ No |
| **Quarterly Exports View** | PostgreSQL VIEW | `v_quarterly_exports` | Aggregates monthly data | ❌ No |
| **Unified Policy View** | PostgreSQL VIEW | `v_export_policy_unified` | Joins 6+ tables | ❌ No |
| **DGFT Policies** | ChromaDB Vector | `dgft_chroma_db/` | Metadata-based search | ✅ Metadata only |
| **Trade Agreements** | FAISS + ChromaDB | `agreements_rag_store/` | Article-aware chunks, cross-ref index | ✅ Metadata only |

---

## 🎯 Key Design Principles

### ✅ **No JSON Columns in SQL**
- All relationships use **foreign keys** and **joins**
- Multi-valued data stored in **separate rows**, not JSON arrays
- Policy conditions stored as **TEXT**, not JSON objects

### ✅ **Relational Integrity**
- Foreign keys enforce data consistency
- Cascading deletes maintain referential integrity
- View layer provides unified access

### ✅ **Metadata in Vector Stores**
- ChromaDB stores metadata directly (no external tables)
- FAISS index paired with `documents.json` and `article_index.json` for metadata and cross-references
- No SQL tables for vector store metadata

### ✅ **View-Based Integration**
- Complex joins pre-defined in views
- Agents query views, not individual tables
- Single source of truth per query type

---

## 🤖 Agent → Storage Mapping

Each agent in `agents/` reads from specific data stores:

| Agent | File | Data Sources |
|-------|------|--------------|
| **QueryRouter** | `agents/router.py` | — (LLM-only, no data access) |
| **SQLAgent** | `agents/sql_agent.py` | `export_statistics`, `monthly_export_statistics`, `v_monthly_exports`, `v_quarterly_exports`, `v_export_policy_unified`, `mv_hs_export_summary`, DB functions |
| **PolicyAgent** | `agents/policy_agent.py` | `prohibited_items`, `restricted_items`, `ste_items`, `v_export_policy_unified` via `ExportDataIntegrator` |
| **VectorAgent** | `agents/vector_agent.py` | `dgft_chroma_db/` (ChromaDB) |
| **AgreementsAgent** | `agents/agreements_agent.py` | `agreements_rag_store/` (FAISS + ChromaDB + article index) via `AgreementsRetriever` |
| **Combined** | `agents/graph.py` | Runs SQL + Policy + Agreements together; also directly queries `prohibited_items`, `restricted_items`, `ste_items`, `itc_chapter_policies` |
| **AnswerSynthesizer** | `agents/synthesizer.py` | — (combines results from other agents, LLM-only) |

## 🔍 Query Examples

### Get HS Code with All Policy Info (Including References)
```sql
SELECT 
    hs_code,
    hs_description,
    itc_policy,
    policy_reference,
    policy_reference_text,
    overall_status,
    is_prohibited,
    is_restricted
FROM v_export_policy_unified
WHERE hs_code = '07131010';
```

### Find All HS Codes with Policy Condition 1
```sql
SELECT hs_code, hs_description, policy_reference_text
FROM v_export_policy_unified
WHERE policy_reference = 'Policy Condition 1';
```

### Get Export Statistics for Multiple Years
```sql
SELECT year_label, country_code, export_value_crore
FROM export_statistics
WHERE hs_code = '070310'
ORDER BY year_label DESC, country_code;
```

### Get Chapter Policy Definitions
```sql
SELECT policy_type, policy_text
FROM itc_chapter_policies
WHERE chapter_code = '07'
ORDER BY policy_type;
```

---

## 📁 File Locations

### SQL Schema Files
- `storage-scripts/hs_codes.sql` - Base HS codes schema
- `storage-scripts/itc_hs_schema.sql` - ITC products, policy references
- `storage-scripts/prohibited_restricted.sql` - Restricted/prohibited items
- `storage-scripts/ste-schema.sql` - STE items schema
- `storage-scripts/export_data_schema.sql` - Trade statistics schema

### Data Loading Scripts
- `storage-scripts/itc_data_loader.py` - ITC data, policy references
- `storage-scripts/restrictions.py` - Prohibited/restricted items
- `storage-scripts/ste_items.py` - STE items
- `storage-scripts/export_data.py` - Annual trade statistics
- `storage-scripts/monthly_trade_loader.py` - Monthly 2024 trade data (xlsx → PostgreSQL)
- `storage-scripts/database_unification.py` - Creates unified views
- `storage-scripts/agreements_ingest_enhanced.py` - Trade agreement PDF ingestion
- `storage-scripts/agreements_retriever.py` - Agreement search with cross-reference resolution

---

## 🚀 Access Patterns

### Application Layer
```python
from export_data_integrator import ExportDataIntegrator

integrator = ExportDataIntegrator()

# Automatically queries v_export_policy_unified
result = integrator.get_hs_code_info('07131010')

# Returns unified data including policy references
print(result['itc_policy']['policy_reference'])  # 'Policy Condition 1'
print(result['itc_policy']['policy_reference_text'])  # Full text
```

### Prefix Matching (6→8 Digit HS Codes)
The `ExportDataIntegrator` supports prefix matching for restriction checks:
```python
# User queries 6-digit code, DB has 8-digit entries
info = integrator.get_hs_code_info('854340')
# Internally uses: WHERE hs_code LIKE '854340%'
# Matches: 85434010, 85434020, etc.
```

This applies to:
- `_check_prohibited()` — prohibited items lookup
- `_check_restricted()` — restricted items lookup
- `_check_ste()` — STE items lookup
- `_get_hs_code_basic()` — basic HS info fallback to `itc_hs_products`

### LangGraph SQL Agent
- Has full schema context for all tables and views
- Generates SQL queries based on user questions
- Uses **conversation history** for context-aware SQL generation
- Queries unified views for comprehensive data

### FastAPI Backend
```bash
python app.py
# API Docs: http://localhost:8000/docs
# Web UI: http://localhost:8000
```

Key endpoints:
- `POST /api/chat` — Chat with multi-agent system (with memory)
- `GET /api/restriction-check?hs_code=854340` — Prefix-aware restriction check
- `POST /api/trade-data` — Trade data for visualizations
- `GET /api/session/{id}/history` — Get conversation history

---

**Last Updated**: February 23, 2026  
**Database Schema Version**: 4.0 (Modular agent refactoring, agents/ package)
