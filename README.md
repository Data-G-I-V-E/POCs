# Export Advisory Multi-Agent System

LangGraph-based export advisory assistant for India-focused export analysis across trade data, policy restrictions, DGFT FTP text, and trade agreements.

## What this app does

- Routes each query to the right agent: SQL, Policy, Agreements, Vector, HS Lookup, or Combined.
- Uses session memory for multi-turn follow-ups (`it`, `same code`, `what about UAE?`).
- Enforces strict trade-data scope for HS codes through guard logic.
- Returns source metadata for traceability (`sql`, `policy_check`, `trade_agreements`, `vector_search`, guard events).

## Current architecture (as implemented)

```text
Web UI (static/)  ->  FastAPI (app.py)  ->  ExportAdvisoryGraph (agents/graph.py)

Graph flow:
router -> one of [sql | policy | agreements | vector | hs_lookup | combined | general]
      -> synthesizer -> END

Combined execution order:
1) SQL Agent (only if query explicitly asks for trade/export data)
2) Policy Agent (HS-level or chapter-level fallback checks)
3) Agreements Agent (if country is available)
4) DGFT FTP retriever supplement
5) Synthesizer
```

## Agents and responsibilities

| Agent | File | Responsibility |
|---|---|---|
| QueryRouter | `agents/router.py` | LLM route classification + HS/country extraction + product→HS lookup + combined auto-upgrade logic |
| SQLAgent | `agents/sql_agent.py` | Text-to-SQL for structured data queries; applies trade HS guard for explicit trade requests |
| PolicyAgent | `agents/policy_agent.py` | Restriction/compliance checks via `ExportDataIntegrator` |
| AgreementsAgent | `agents/agreements_agent.py` | FTA retrieval (Qdrant first, FAISS fallback), direct article lookup, cross-ref enrichment |
| VectorAgent | `agents/vector_agent.py` | DGFT FTP retrieval (Qdrant first, FAISS fallback), section lookup, optional agreements supplement |
| HSLookupAgent | `agents/hs_lookup_agent.py` | HS master search (exact/prefix/FTS/ILIKE/trigram) with clarification states |
| AnswerSynthesizer | `agents/synthesizer.py` | Merges invoked agent outputs into final markdown response |
| TradeGuard utilities | `agents/trade_guard.py` | Explicit trade-intent detection + HS scope validation |

## Routing and guard rules

### 1) DGFT article/section disambiguation

- Queries like `DGFT FTP Article 8.04` are treated as policy-document retrieval (`vector` path).
- They are not treated as HS chapter/trade-data queries.

### 2) Trade data execution is explicit

- In `combined`, SQL runs only when trade intent is explicit (e.g., `trade data`, `export statistics`, `monthly exports`).
- Policy/agreements/vector can still run for compliance/policy questions without trade SQL.

### 3) HS scope for trade data

Trade data is constrained to the configured HS-6 allowlist in `Config.FOCUS_HS_CODES`:

`070310, 070700, 070960, 080310, 080410, 080450, 610910, 610342, 610442, 620342, 620462, 620520, 850440, 851310, 851762, 902610`

Validation behavior:

- `6–8 digit` HS that maps to allowed HS-6 -> allowed
- `<6 digit` prefix matching allowed codes (example `08`) -> ask for `6–8 digit HS code`
- unsupported HS (example `900219`) -> guarded message with allowed list

## API behavior (current)

### Core endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/chat` | Main conversational query endpoint |
| `GET` | `/api/health` | Backend/agent readiness |
| `GET` | `/api/session/{id}/history` | Session message history |
| `DELETE` | `/api/session/{id}` | Clear one session |
| `GET` | `/api/sessions` | List active sessions |

### Data endpoints

| Method | Endpoint | Current semantics |
|---|---|---|
| `POST` | `/api/trade-data` | Validates HS input via guard; returns exact HS-6 aggregates only |
| `POST` | `/api/monthly-trade-data` | Validates HS input via guard; returns exact HS-6 monthly series |
| `GET` | `/api/hs-code/{hs_code}` | HS-level policy information |
| `GET` | `/api/export-check` | Export feasibility by HS + country |
| `GET` | `/api/restriction-check` | Restriction/prohibition/STE status |
| `GET` | `/api/focus-codes` | Allowed HS-6 trade scope |

Guarded data responses return HTTP 200 with payload flags:

```json
{
  "guarded": true,
  "guard_status": "needs_6_to_8_digit|not_allowed|missing_hs",
  "message": "...",
  "data": []
}
```

## Data layer summary

- **PostgreSQL**: structured trade/policy/HS tables and views.
- **Qdrant + FastEmbed (primary retrievers)**: agreements + DGFT FTP semantic retrieval.
- **FAISS/Chroma local artifacts (fallback)**: `agreements_rag_store/`, `dgft_ftp_rag_store/`.

## Quick start

### 1) Install

```bash
pip install -r requirements.txt
```

### 2) Configure `.env`

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=PPL-AI
DB_USER=postgres
DB_PASSWORD=your_password

ANTHROPIC_API_KEY=your_key

# Optional (for Qdrant retrievers)
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
```

### 3) DB setup and loaders

```bash
python storage-scripts/run_schema.py
python storage-scripts/itc_data_loader.py
python storage-scripts/restrictions.py
python storage-scripts/ste_items.py
python storage-scripts/database_unification.py
python storage-scripts/monthly_trade_loader.py
```

### 4) Build retrieval stores

Preferred (Qdrant ingestion):

```bash
python storage-scripts/agreements_ingest_qdrant.py
python storage-scripts/dgft_ftp_ingest_qdrant.py
```

Fallback local FAISS/Chroma ingestion:

```bash
python storage-scripts/agreements_ingest_enhanced.py
python storage-scripts/dgft_ftp_ingest.py
```

### 5) Run

```bash
python app.py
```

- UI: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

## Example queries

- `Explain DGFT FTP Article 8.04`
- `Can I export HS 070310 to Australia?`
- `Show trade data for HS 080410`
- `Show monthly exports for 850440 to UAE`
- `Rules of origin for textiles under India-UAE CEPA`

## Project structure (important files)

```text
app.py
config.py
export_data_integrator.py
langgraph_export_agent.py

agents/
  graph.py
  router.py
  trade_guard.py
  sql_agent.py
  policy_agent.py
  agreements_agent.py
  vector_agent.py
  hs_lookup_agent.py
  synthesizer.py
  state.py

prompts/
  router_prompt.py
  sql_prompt.py
  sql_schema.py
  synthesizer_prompt.py

static/
  index.html
  styles.css
  app.js
```

## Related docs

- `LANGGRAPH_GUIDE.md`: detailed graph flow and agent behavior
- `DATA_STORAGE.md`: storage topology, tables/views, retrieval backends

---

Last updated: 2026-03-19