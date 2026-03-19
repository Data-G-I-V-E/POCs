# Data Storage Architecture

This document describes where data lives, how agents access it, and what constraints are enforced by the current app.

## 1) Storage layers

## 1.1 PostgreSQL (structured)

Primary source for:

- HS/product metadata
- annual + monthly trade statistics
- restriction/prohibition/STE policy tables
- chapter policies/notes
- integration views used by SQL/policy logic

Configured via `Config.DB_CONFIG` in `config.py`.

## 1.2 Vector retrieval (semantic)

Runtime retrievers are Qdrant-first, with local fallback:

- **Agreements**
  - primary: `storage-scripts/agreements_retriever_qdrant.py` (Qdrant + FastEmbed)
  - fallback: `storage-scripts/agreements_retriever.py` (FAISS/Chroma)

- **DGFT FTP**
  - primary: `storage-scripts/dgft_ftp_retriever_qdrant.py` (Qdrant + FastEmbed)
  - fallback: `storage-scripts/dgft_ftp_retriever.py` (FAISS/Chroma)

## 1.3 Local retrieval artifacts (on disk)

- `agreements_rag_store/` (documents/index/metadata)
- `dgft_ftp_rag_store/` (documents/index/metadata)

These are used by fallback retrievers and also provide metadata indexes (article/section maps).

## 2) Structured database objects used by agents

## 2.1 Trade data tables/views

- `export_statistics` (annual)
- `monthly_export_statistics` (monthly)
- `v_monthly_exports`
- `v_quarterly_exports`

Used by: SQL workflows and chart endpoints.

## 2.2 Policy and restriction tables

- `v_export_policy_unified`
- `prohibited_items`
- `restricted_items`
- `ste_items`
- `itc_chapter_policies`
- `itc_chapter_notes`
- `itc_chapters`

Used by: Policy agent and combined chapter-level fallback checks.

## 2.3 HS reference/search tables

- `hs_master_8_digit` (full HS lookup table searched by router/HS lookup agent)
- `itc_hs_products`
- `hs_codes` (focus/normalized hierarchy table used by integrator and joins)

## 3) Trade-data scope constraints (critical)

Trade-data requests are intentionally constrained to a fixed HS-6 allowlist (`Config.FOCUS_HS_CODES`):

- `070310, 070700, 070960`
- `080310, 080410, 080450`
- `610910, 610342, 610442`
- `620342, 620462, 620520`
- `850440, 851310, 851762`
- `902610`

## 3.1 Enforcement points

1. `agents/trade_guard.py`
   - detects explicit trade intent
   - validates HS input and prefix handling

2. `agents/sql_agent.py`
   - guards explicit trade SQL queries before execution

3. `app.py`
   - `/api/trade-data` and `/api/monthly-trade-data` validate input through `_validate_trade_data_input`
   - guarded responses are returned as HTTP 200 with:
     - `guarded: true`
     - `guard_status: needs_6_to_8_digit|not_allowed|missing_hs`
     - `message`

## 3.2 Practical effect

- Chapter/prefix-only inputs like `08` do not return trade rows.
- Users are prompted to provide a `6–8 digit` HS code.
- Unsupported HS values (example `900219`) return guarded no-data responses.

## 4) Agent-to-storage mapping

| Agent | Main storage dependencies |
|---|---|
| `QueryRouter` | LLM prompt + HS lookups (`hs_master_8_digit`, policy tables for fallback matching) |
| `SQLAgent` | PostgreSQL trade/policy views; guarded by trade HS validator |
| `PolicyAgent` | `ExportDataIntegrator` over policy/restriction/chapter tables |
| `AgreementsAgent` | Qdrant agreements collection (fallback local agreements store + article index) |
| `VectorAgent` | Qdrant DGFT collection (fallback local DGFT store + section index), optional agreements supplement |
| `HSLookupAgent` | `hs_master_8_digit` + supplemental ITC product search |
| `Combined` | Conditional SQL + policy checks + agreements + DGFT retrieval |
| `Synthesizer` | No direct storage; merges state outputs |

## 5) Retrieval collections and config

From `config.py`:

- `QDRANT_URL`
- `QDRANT_API_KEY`
- `QDRANT_AGREEMENTS_COLLECTION` (default: `trade_agreements`)
- `QDRANT_DGFT_COLLECTION` (default: `dgft_ftp`)
- `QDRANT_EMBEDDING_MODEL` (default: `all-MiniLM-L6-v2`)

## 6) Source data directories (workspace)

- `data/agreements/{australia,uae,uk}`
- `data/policies/DGFT_FTP`
- `data/trade_data/dgft_tradestat/`
- `data/hs_codes`

## 7) Ingestion and refresh workflow

## 7.1 SQL schema/load

```bash
python storage-scripts/run_schema.py
python storage-scripts/itc_data_loader.py
python storage-scripts/restrictions.py
python storage-scripts/ste_items.py
python storage-scripts/database_unification.py
python storage-scripts/monthly_trade_loader.py
```

## 7.2 Retrieval indexes

Preferred (Qdrant):

```bash
python storage-scripts/agreements_ingest_qdrant.py
python storage-scripts/dgft_ftp_ingest_qdrant.py
```

Fallback (local artifacts for FAISS/Chroma retrievers):

```bash
python storage-scripts/agreements_ingest_enhanced.py
python storage-scripts/dgft_ftp_ingest.py
```

## 8) Notes for maintainers

- Keep the HS allowlist in `Config.FOCUS_HS_CODES` synchronized with any trade-data dataset expansion.
- If trade data is added for new HS codes, update:
  - `Config.FOCUS_HS_CODES`
  - any prompt/documentation references to allowed trade scope.
- If retriever backend strategy changes, update this file and `README.md` together.

---

Last updated: 2026-03-19