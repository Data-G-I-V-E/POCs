# Export Advisory Multi-Agent System

LangGraph-based export advisory assistant for India-focused export analysis. Covers trade statistics, export policy restrictions (prohibited/restricted/STE), DGFT Foreign Trade Policy text, and bilateral trade agreements (India-Australia ECTA, India-UAE CEPA, India-UK FTA).

## What this app does

- Classifies each query and routes it to the right agent(s): SQL, Policy, Agreements, Vector (DGFT FTP), HS Lookup, or Combined.
- Maintains per-session conversation history so follow-ups like "what about UAE?" or "same code" resolve correctly.
- Enforces strict scope gating: trade-data SQL only runs when the user explicitly asks for data, and only for HS codes in the configured allowlist.
- Returns source metadata for every response (`sql`, `policy_check`, `trade_agreements`, `vector_search`, `trade_data_guard`) so answers are traceable.
- Displays export trade data for both 2023-24 and 2024-25 fiscal years in charts and tables.

## System architecture

```
Browser (static/index.html + app.js)
    |  HTTP POST /api/chat
    v
FastAPI  (app.py)
    |  integrator.query(user_query, session_id)
    v
ExportAdvisoryGraph  (agents/graph.py)
    |
    +--[StateGraph entry]--> QueryRouter (agents/router.py)
                                 |
              +------------------+------------------+
              |       |       |       |       |      |
             sql  policy  vector  agree  hs_lkp  combined
              |       |       |       |       |      |
              +-------+-------+-------+-------+------+
                                 |
                          AnswerSynthesizer (agents/synthesizer.py)
                                 |
                               [END]
```

### Combined node execution order (agents/graph.py `_combined_execute`)

1. **SQL Agent** — only if query explicitly mentions trade data / statistics
2. **Policy Agent** — direct HS-level check via `ExportDataIntegrator` (or chapter-level batch if no HS code)
3. **Agreements Agent** — FTA retrieval if a country is present in state
4. **DGFT FTP search** — always runs via `VectorAgent.dgft_retriever.search()` (top-3 docs)
5. Routes state to `synthesizer`

## Agent responsibilities

| Agent | File | What it does |
|---|---|---|
| `QueryRouter` | `agents/router.py` | LLM route classification → deterministic overrides → HS extraction → context carry-over → product→HS DB search → combined auto-upgrade |
| `SQLAgent` | `agents/sql_agent.py` | Text-to-SQL (LLM prompt) → psycopg2 execution → trade guard check before execution |
| `PolicyAgent` | `agents/policy_agent.py` | Calls `ExportDataIntegrator.get_hs_code_info()` or `can_export_to_country()` depending on whether a country is in state |
| `AgreementsAgent` | `agents/agreements_agent.py` | Semantic search over FTA articles (Qdrant primary, FAISS fallback); direct article lookup + cross-reference enrichment |
| `VectorAgent` | `agents/vector_agent.py` | DGFT FTP semantic retrieval (Qdrant primary, FAISS fallback); section lookup and chapter-filtered retrieval |
| `HSLookupAgent` | `agents/hs_lookup_agent.py` | 7-strategy HS code search against `hs_master_8_digit`; returns clarification mode when ambiguous |
| `AnswerSynthesizer` | `agents/synthesizer.py` | Merges all agent outputs into markdown; applies flag-based policy decision (no LLM for policy status) |
| `ExportAdvisoryGraph` | `agents/graph.py` | LangGraph wiring, session memory (`dict[session_id → list[BaseMessage]]`), `_combined_execute` logic |
| Trade guard | `agents/trade_guard.py` | `is_explicit_trade_data_request()`, `validate_trade_hs_request()`, `is_ftp_policy_reference_query()` |

## Policy decision logic (synthesizer)

The synthesizer does **not** use CHECK_POLICY or any LLM judgment for export status. It reads three boolean flags from `policy_results` directly:

```
is_prohibited = False  AND  is_restricted = False  AND  is_ste = False
    → "FREE — not found in prohibited, restricted, or STE lists"

is_prohibited = True
    → "PROHIBITED: <description> — <policy_condition>"

is_restricted = True
    → "RESTRICTED: <description> — <policy_condition>"

is_ste = True
    → "STE: Export only via <authorized_entity> — <policy_condition>"
```

## Trade data scope guard

Trade-data requests (SQL and chart endpoints) are constrained to a fixed HS-6 allowlist (`Config.FOCUS_HS_CODES`):

```
Agriculture:   070310  070700  070960  080310  080410  080450
Textiles:      610910  610342  610442  620342  620462  620520
Electronics:   850440  851310  851762
Instruments:   902610
```

Guard validation results:

| Status | Trigger | Response |
|---|---|---|
| `ok` | 6–8 digit HS whose HS-6 prefix is in allowlist | proceeds normally |
| `needs_6_to_8_digit` | short prefix (e.g. `08`) matches allowlist codes | ask for 6–8 digit HS |
| `not_allowed` | 6+ digit HS whose HS-6 is not in allowlist | guarded message with allowed list |
| `missing_hs` | no HS code found in query or session | ask for HS code |

Guard is enforced at three layers: `trade_guard.py`, `sql_agent.py`, and `/api/trade-data` + `/api/monthly-trade-data` in `app.py`.

## API endpoints

### Chat

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/chat` | Main conversational endpoint; returns `answer`, `sources`, `query_type`, `hs_code`, `country`, `session_id` |
| `GET` | `/api/health` | Backend readiness check |
| `GET` | `/api/session/{id}/history` | Full session message history |
| `DELETE` | `/api/session/{id}` | Clear one session |
| `GET` | `/api/sessions` | List active session IDs |

### Data visualization endpoints

| Method | Endpoint | Returns |
|---|---|---|
| `POST` | `/api/trade-data` | Annual export data: `data_by_year` (keyed by `'2023-2024'` / `'2024-2025'`), `years`, `countries`, backward-compat `data` |
| `POST` | `/api/monthly-trade-data` | Monthly export data: `monthly_data` keyed by country; each entry has `value` (2024-25), `prev_year_value` (2023-24), `growth_pct`, `ytd_value`, `month_name` |
| `GET` | `/api/hs-code/{hs_code}` | HS-level policy info via `ExportDataIntegrator` |
| `GET` | `/api/export-check` | Export feasibility (`can_export`, `issues`, `warnings`) |
| `GET` | `/api/restriction-check` | Prohibited / restricted / STE status flags |
| `GET` | `/api/focus-codes` | Allowed HS-6 trade scope list |

Guarded responses are HTTP 200 with:
```json
{ "guarded": true, "guard_status": "...", "message": "...", "data": [] }
```

## Data stores

| Store | Technology | Used for |
|---|---|---|
| Primary DB | PostgreSQL (Supabase in production) | All structured tables — HS codes, trade stats, policy restrictions, chapter notes |
| Agreements vector | Qdrant + `all-MiniLM-L6-v2` (FastEmbed) | Semantic search over FTA articles |
| DGFT FTP vector | Qdrant + `all-MiniLM-L6-v2` (FastEmbed) | Semantic search over DGFT FTP sections |
| Agreements fallback | FAISS / Chroma (`agreements_rag_store/`) | Local fallback if Qdrant unavailable |
| DGFT FTP fallback | FAISS / Chroma (`dgft_ftp_rag_store/`) | Local fallback if Qdrant unavailable |

DB connection priority: `SUPABASE_CONNECTION_STRING` (full libpq URI with SSL) → individual `DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD` env vars.

## Quick start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Configure `.env`

```env
# Supabase (production) — takes priority over individual vars below
SUPABASE_CONNECTION_STRING=postgresql://user:pass@host:5432/dbname

# Local dev fallback
DB_HOST=localhost
DB_PORT=5432
DB_NAME=PPL-AI
DB_USER=postgres
DB_PASSWORD=your_password

ANTHROPIC_API_KEY=your_key

# Qdrant (required for semantic retrieval)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=

# Optional overrides
LLM_MODEL=claude-sonnet-4-20250514
LLM_TEMPERATURE=0.1
QDRANT_AGREEMENTS_COLLECTION=trade_agreements
QDRANT_DGFT_COLLECTION=dgft_ftp
QDRANT_EMBEDDING_MODEL=all-MiniLM-L6-v2
```

### 3. Load structured data into PostgreSQL

```bash
python storage-scripts/run_schema.py           # creates all tables and views
python storage-scripts/itc_data_loader.py      # ITC-HS products, chapters, policies, notes
python storage-scripts/restrictions.py         # prohibited_items + restricted_items
python storage-scripts/ste_items.py            # ste_items (STE canalized goods)
python storage-scripts/hs_master_loader_v2.py  # hs_master_8_digit (12k+ codes)
python storage-scripts/database_unification.py # hs_codes unified view
python storage-scripts/monthly_trade_loader.py # monthly_export_statistics (2023-24 + 2024-25)
```

### 4. Build vector indexes

Qdrant (preferred):
```bash
python storage-scripts/agreements_ingest_qdrant.py
python storage-scripts/dgft_ftp_ingest_qdrant.py
```

Local fallback (FAISS/Chroma):
```bash
python storage-scripts/agreements_ingest_enhanced.py
python storage-scripts/dgft_ftp_ingest.py
```

### 5. Run

```bash
python app.py
```

- UI: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

## Example queries

```
Can I export HS 070310 to Australia?
Show monthly export statistics for 850440 to UAE
What are the rules of origin for textiles under India-UAE CEPA?
Is iron ore fines restricted?
Explain DGFT FTP Article 8.04
What is the HS code for sillimanite fines?
Show trade data for HS 080410
```

## Project structure

```
app.py                          FastAPI server + all HTTP endpoints
config.py                       Centralized config (env → Config class)
export_data_integrator.py       Core policy + HS lookup logic (used by PolicyAgent)
langgraph_export_agent.py       CLI entry point / demo runner

agents/
  graph.py                      LangGraph wiring + session memory + _combined_execute
  router.py                     Query classification, HS extraction, product→HS lookup
  sql_agent.py                  Text-to-SQL with trade guard
  policy_agent.py               Calls ExportDataIntegrator for policy checks
  agreements_agent.py           FTA retrieval (Qdrant + FAISS fallback)
  vector_agent.py               DGFT FTP retrieval (Qdrant + FAISS fallback)
  hs_lookup_agent.py            7-strategy HS code search
  synthesizer.py                Flag-based policy decision + LLM response synthesis
  trade_guard.py                Explicit trade intent + HS scope validation
  state.py                      AgentState TypedDict definition

prompts/
  router_prompt.py              LLM prompt for route classification + entity extraction
  sql_prompt.py                 LLM prompt for text-to-SQL generation
  sql_schema.py                 DB schema context injected into SQL prompt
  synthesizer_prompt.py         LLM prompt for final answer synthesis

storage-scripts/
  run_schema.py                 Schema DDL runner
  itc_data_loader.py            ITC-HS products + chapter data
  restrictions.py               Prohibited + restricted items
  ste_items.py                  STE (canalized) items
  hs_master_loader_v2.py        Full HS master table (8-digit codes)
  database_unification.py       Unified hs_codes table
  monthly_trade_loader.py       Monthly trade stats from DGFT Excel files
  agreements_ingest_qdrant.py   FTA → Qdrant ingestion
  dgft_ftp_ingest_qdrant.py     DGFT FTP → Qdrant ingestion
  agreements_retriever_qdrant.py  Qdrant-based FTA retriever
  dgft_ftp_retriever_qdrant.py    Qdrant-based DGFT FTP retriever
  agreements_ingest_enhanced.py   FTA → FAISS/Chroma ingestion (fallback)
  dgft_ftp_ingest.py              DGFT FTP → FAISS/Chroma ingestion (fallback)

static/
  index.html                    Single-page UI
  app.js                        Chat UI, Chart.js bar + line charts, table rendering
  styles.css                    Dark-theme styling

data/
  agreements/{australia,uae,uk}/  Source FTA PDF/text files
  policies/DGFT_FTP/              DGFT FTP source documents
  trade_data/dgft_tradestat/      Raw DGFT Excel trade stat files
  hs_codes/                       HS code reference CSVs
```

## Related docs

- [LANGGRAPH_GUIDE.md](LANGGRAPH_GUIDE.md) — exact graph flow, router logic, agent behavior
- [DATA_STORAGE.md](DATA_STORAGE.md) — all DB tables/views, ingestion workflow, retrieval backends

---

Last updated: 2026-03-24
