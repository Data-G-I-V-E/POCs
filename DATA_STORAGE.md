# Data Storage Architecture

Exact reference for where data lives, how it is loaded, how agents access it, and what constraints are enforced. Code is authoritative; this document reflects the current implementation.

---

## 1. Storage layers

### 1.1 PostgreSQL (structured data)

All structured data lives in PostgreSQL. In production the instance is hosted on Supabase.

Connection resolved in `config.py`:
```
SUPABASE_CONNECTION_STRING (full libpq URI, SSL required)
  → parsed into DB_CONFIG: host, port, database, user, password, sslmode=require

Fallback (local dev):
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD env vars
```

Every script in `storage-scripts/` reads `SUPABASE_CONNECTION_STRING` first and falls back to individual vars. All psycopg2 connections use `Config.DB_CONFIG`.

### 1.2 Qdrant (vector retrieval — primary)

- Endpoint: `Config.QDRANT_URL` (default `http://localhost:6333`)
- Auth: `Config.QDRANT_API_KEY` (blank for local)
- Embedding model: `Config.QDRANT_EMBEDDING_MODEL` (default `all-MiniLM-L6-v2`, run via FastEmbed locally)
- Collections:
  - `Config.QDRANT_AGREEMENTS_COLLECTION` (default `trade_agreements`) — FTA articles
  - `Config.QDRANT_DGFT_COLLECTION` (default `dgft_ftp`) — DGFT FTP sections

### 1.3 FAISS / Chroma (vector retrieval — local fallback)

Used when Qdrant is unavailable. Artifacts on disk:

| Directory | Content |
|---|---|
| `agreements_rag_store/` | FAISS index + document store + article metadata index |
| `dgft_ftp_rag_store/` | FAISS/Chroma index + document store + section metadata index |

Agents try Qdrant first and fall back to local store silently.

---

## 2. PostgreSQL tables and views

### 2.1 HS code reference tables

| Table | Description | Loaded by |
|---|---|---|
| `hs_master_8_digit` | 12,000+ HS codes at 8-digit level with `chapter`, `code_level`, `parent_code`, `description` | `hs_master_loader_v2.py` |
| `hs_codes` | Unified/normalized HS hierarchy table used by `ExportDataIntegrator` joins | `database_unification.py` |
| `itc_hs_products` | ITC-HS product list with `export_policy` field | `itc_data_loader.py` |

`hs_master_8_digit` has a `pg_trgm` GIN index on `description` for trigram similarity search. `HSLookupAgent` uses both FTS (`plainto_tsquery`) and `word_similarity()` strategies against this table.

### 2.2 ITC chapter/policy tables

| Table | Description | Loaded by |
|---|---|---|
| `itc_chapters` | Chapter codes + chapter names | `itc_data_loader.py` |
| `itc_chapter_notes` | Per-chapter notes: `note_type` (`main_notes`, `policy_conditions`, `export_licensing`), `sl_no`, `note_text` | `itc_data_loader.py` |
| `itc_chapter_policies` | Chapter-level export policy conditions: `chapter_code`, `policy_type`, `policy_text` | `itc_data_loader.py` |

### 2.3 Export restriction tables

These three tables are the source of truth for export status. All have a `policy_condition` column.

| Table | Description | Columns |
|---|---|---|
| `prohibited_items` | Absolutely prohibited exports | `hs_code`, `description`, `policy_condition` |
| `restricted_items` | Restricted exports (require license/conditions) | `hs_code`, `description`, `policy_condition` |
| `ste_items` | Canalized exports (State Trading Enterprise only) | `hs_code`, `description`, `export_policy`, `policy_condition`, `authorized_entity` |

Loaded by `restrictions.py` (prohibited + restricted) and `ste_items.py`. All scripts use `ON CONFLICT DO UPDATE` so re-runs are idempotent. The `prohibited_restricted.sql` file contains the full DDL + INSERT statements for direct Supabase SQL editor execution.

`ExportDataIntegrator._check_prohibited/restricted/ste()` queries each table in order: exact `hs_code = ANY(candidates)` match first, then prefix `LIKE '{hs6}%'` fallback for 6-digit queries matching 8-digit entries.

### 2.4 Policy view

| View | Description |
|---|---|
| `v_export_policy_unified` | Joins `itc_hs_products`, `prohibited_items`, `restricted_items`, `ste_items`. Returns `overall_status` field (FREE/PROHIBITED/RESTRICTED/STE_ONLY/CONDITIONAL/CHECK_POLICY). **Not used for policy decisions** — the synthesizer uses the raw flags from `_check_prohibited/restricted/ste()` directly. |

### 2.5 Trade statistics tables

| Table | Schema | Notes |
|---|---|---|
| `export_statistics` | `hs_code`, `country_name`, `year_label` (e.g. `'2023-2024'`), `export_value_crore` | Annual data; `year_label` is a string like `'2024-2025'` |
| `monthly_export_statistics` | `hs_code`, `country_name`, `year` (integer, e.g. `2024`), `month` (1–12), `month_name`, `export_value_crore` (2024-25 value), `prev_year_value_crore` (2023-24 value) | Both fiscal years stored in every row |

The `year` column holds the current year (2024). Current year exports are in `export_value_crore`; prior year (2023-24) exports are in `prev_year_value_crore`.

Loaded by `monthly_trade_loader.py` which reads DGFT Excel files from `data/trade_data/dgft_tradestat/2024/`. The Excel columns `M-2024(R)` → `export_value_crore` and `M-2023(R)` → `prev_year_value_crore`.

### 2.6 Trade statistics views

| View | Description |
|---|---|
| `v_monthly_exports` | Joins `monthly_export_statistics` + country normalization. Columns include `country_name`, `month`, `month_name`, `export_value_crore`, `prev_year_value_crore`, `monthly_growth_pct`, `ytd_value_crore` |
| `v_quarterly_exports` | Aggregates monthly data into quarters |

`/api/monthly-trade-data` queries `v_monthly_exports` and returns both `value` (2024-25) and `prev_year_value` (2023-24) per month per country.

---

## 3. Trade-data scope constraint

Trade-data endpoints and SQL execution are gated to a fixed HS-6 allowlist (`Config.FOCUS_HS_CODES`):

```
Agriculture:  070310  070700  070960   (Onions, Guar, Okra)
              080310  080410  080450   (Bananas, Dates, Guavas)
Textiles:     610910  610342  610442   (T-shirts, Trousers, Dresses knit)
              620342  620462  620520   (Trousers, Suits woven)
Electronics:  850440  851310  851762   (Transformers, Flashlights, Phones)
Instruments:  902610                   (Flow meters)
```

Enforcement points:

| Layer | Where | How |
|---|---|---|
| SQL agent | `agents/sql_agent.py` | `validate_trade_hs_request()` before any SQL execution |
| API endpoint | `app.py _validate_trade_data_input()` | Validates `/api/trade-data` and `/api/monthly-trade-data` requests |
| Router | `agents/trade_guard.py` | `is_explicit_trade_data_request()` gates whether SQL runs in combined |

Guard returns HTTP 200 with `guarded: true`, not an error status, so the UI can display a user-friendly message.

---

## 4. Vector store contents

### 4.1 Trade agreements (Qdrant `trade_agreements` collection)

Source documents in `data/agreements/{australia,uae,uk}/`:

| Agreement | Coverage |
|---|---|
| India-Australia ECTA | Tariff schedules, rules of origin, services, investment |
| India-UAE CEPA | Goods, services, origin rules, customs procedures |
| India-UK FTA | (in progress/available documents) |

Ingest: `storage-scripts/agreements_ingest_qdrant.py`
Retriever: `storage-scripts/agreements_retriever_qdrant.py`

Each chunk stored with metadata: `agreement`, `country`, `article`, `doc_type`, `cross_ref_articles`, `filename`.

### 4.2 DGFT Foreign Trade Policy (Qdrant `dgft_ftp` collection)

Source documents in `data/policies/DGFT_FTP/`:
- DGFT FTP chapters (Chapter 1 through 9+)
- Handbook of Procedures (HBP)

Ingest: `storage-scripts/dgft_ftp_ingest_qdrant.py`
Retriever: `storage-scripts/dgft_ftp_retriever_qdrant.py`

Each chunk stored with metadata: `chapter`, `chapter_num`, `section_id`, `section_full`, `filename`.

---

## 5. Agent-to-storage mapping

| Agent | Storage accessed | How |
|---|---|---|
| `QueryRouter` | `hs_master_8_digit`, `restricted_items`, `prohibited_items`, `ste_items` | `HSLookupAgent.search_by_description()` + `_search_policy_tables_by_description()` |
| `SQLAgent` | All PostgreSQL tables (via generated SQL) | `psycopg2.connect(**Config.DB_CONFIG)` |
| `PolicyAgent` | `hs_codes`, `itc_hs_products`, `prohibited_items`, `restricted_items`, `ste_items`, `itc_chapter_notes`, `itc_chapter_policies` | `ExportDataIntegrator` methods |
| `AgreementsAgent` | Qdrant `trade_agreements` (fallback: `agreements_rag_store/`) | `agreements_retriever_qdrant` or `agreements_retriever` |
| `VectorAgent` | Qdrant `dgft_ftp` (fallback: `dgft_ftp_rag_store/`) | `dgft_ftp_retriever_qdrant` or `dgft_ftp_retriever` |
| `HSLookupAgent` | `hs_master_8_digit` | Direct psycopg2 with 7-strategy search |
| `combined` (graph.py) | All of the above conditionally | Delegates to sub-agents + direct DB queries for chapter batch |
| `AnswerSynthesizer` | None | Reads only from `AgentState` fields |

---

## 6. Source data directories

```
data/
  agreements/
    australia/   India-Australia ECTA documents
    uae/         India-UAE CEPA documents
    uk/          India-UK FTA documents
  policies/
    DGFT_FTP/    DGFT Foreign Trade Policy chapters + HBP
    ITC_HS_notifications/   ITC-HS schedule notifications
  trade_data/
    dgft_tradestat/
      2024/      DGFT monthly Excel files (contains both 2023-24 and 2024-25 columns)
  hs_codes/      HS code reference CSVs
```

---

## 7. Ingestion and refresh workflow

### 7.1 PostgreSQL (run in order)

```bash
# 1. Schema — creates all tables, views, indexes
python storage-scripts/run_schema.py

# 2. ITC product/chapter data
python storage-scripts/itc_data_loader.py

# 3. Restriction tables (prohibited + restricted items)
python storage-scripts/restrictions.py
# OR run storage-scripts/prohibited_restricted.sql directly in Supabase SQL editor

# 4. STE items (canalized goods)
python storage-scripts/ste_items.py
# OR run storage-scripts/ste-schema.sql directly in Supabase SQL editor

# 5. Full HS master table (12k+ 8-digit codes)
python storage-scripts/hs_master_loader_v2.py

# 6. Unified hs_codes table
python storage-scripts/database_unification.py

# 7. Monthly trade statistics (2023-24 + 2024-25)
python storage-scripts/monthly_trade_loader.py
```

All scripts support `SUPABASE_CONNECTION_STRING` for direct Supabase loading.

### 7.2 Vector indexes

Qdrant (preferred — required for production semantic search):
```bash
python storage-scripts/agreements_ingest_qdrant.py
python storage-scripts/dgft_ftp_ingest_qdrant.py
python storage-scripts/create_qdrant_indexes.py   # optional: payload + vector indexes
```

Local fallback (FAISS/Chroma — used when Qdrant is down):
```bash
python storage-scripts/agreements_ingest_enhanced.py
python storage-scripts/dgft_ftp_ingest.py
```

---

## 8. Key schema notes for maintainers

- **Adding new HS codes to trade data**: update `Config.FOCUS_HS_CODES`, `Config.FOCUS_CHAPTERS`, load data via `monthly_trade_loader.py`, and update `prompts/sql_schema.py` if needed.
- **Adding a new restriction**: insert into `restricted_items` or `prohibited_items` with `policy_condition`. The policy check (`_check_restricted/_check_prohibited`) will find it immediately — no code change needed.
- **Adding a new STE item**: insert into `ste_items` with `authorized_entity` + `policy_condition`. The 6-digit prefix match means adding one 6-digit parent row covers all 8-digit children.
- **New trade agreement**: add documents to `data/agreements/{country}/`, re-run `agreements_ingest_qdrant.py`. Update `Config.TARGET_COUNTRIES` and `Config.COUNTRY_CODES` if it's a new country.
- **`overall_status = CHECK_POLICY`**: this is a data gap in `itc_hs_products.export_policy` (the code is not explicitly tagged Free). It is not used for policy decisions — the synthesizer uses only the `is_prohibited / is_restricted / is_ste` flags from the three restriction tables.
- **Monthly data columns**: `export_value_crore` = 2024-25 value; `prev_year_value_crore` = 2023-24 value. The `year` integer column holds `2024` for the current dataset.

---

Last updated: 2026-03-24
