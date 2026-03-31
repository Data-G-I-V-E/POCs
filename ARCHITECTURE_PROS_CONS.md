# Architecture Pros & Cons — Export Advisory Multi-Agent System

> **Scope:** This document covers the full system as it exists in the codebase — FastAPI backend, LangGraph orchestration, Claude LLM integration, PostgreSQL data layer, Qdrant/FAISS vector stores, session memory, HS code lookup, trade guard enforcement, and the frontend SPA.

---

## Table of Contents

1. [System Overview (Quick Reference)](#1-system-overview-quick-reference)
2. [LangGraph Multi-Agent Orchestration](#2-langgraph-multi-agent-orchestration)
3. [Session Memory & State Management](#3-session-memory--state-management)
4. [HS Code Lookup & Classification](#4-hs-code-lookup--classification)
5. [Query Routing](#5-query-routing)
6. [SQL Agent & Text-to-SQL](#6-sql-agent--text-to-sql)
7. [Policy Agent & Export Restrictions](#7-policy-agent--export-restrictions)
8. [Vector Search (Qdrant + FAISS/Chroma Fallback)](#8-vector-search-qdrant--faischroma-fallback)
9. [Trade Data Scope Guard](#9-trade-data-scope-guard)
10. [Database Design (PostgreSQL)](#10-database-design-postgresql)
11. [Answer Synthesizer](#11-answer-synthesizer)
12. [API Design (FastAPI)](#12-api-design-fastapi)
13. [Configuration & Environment Management](#13-configuration--environment-management)
14. [Frontend (Static SPA)](#14-frontend-static-spa)
15. [Data Ingestion Pipeline](#15-data-ingestion-pipeline)
16. [Overall Architectural Trade-offs Summary](#16-overall-architectural-trade-offs-summary)

---

## 1. System Overview (Quick Reference)

```
Browser (static SPA)
    ↓ POST /api/chat
FastAPI (app.py)
    ↓
ExportAdvisoryGraph (LangGraph StateGraph)
    ↓
QueryRouter → [SQLAgent | PolicyAgent | VectorAgent | AgreementsAgent | HSLookupAgent | Combined]
    ↓
AnswerSynthesizer (Claude LLM)
    ↓
Response (markdown + sources JSON)
```

**Storage layers:**
- PostgreSQL (Supabase) — HS codes, trade stats, restrictions, STE items
- Qdrant — Trade agreement + DGFT FTP vector embeddings
- FAISS/Chroma — Local fallback vector stores
- In-process Python dict — Session conversation history

---

## 2. LangGraph Multi-Agent Orchestration

### Pros

**Explicit, auditable routing**
Each query follows a visible path: Router → Specialized Agent(s) → Synthesizer. The `next_agent` field in `AgentState` makes the routing decision inspectable in logs and debuggable without stepping through LLM reasoning.

**Clean separation of concerns**
Each agent has a single responsibility (SQL, policy, vector search, HS lookup). This means bugs in one agent cannot silently corrupt results from another. A failure in `SQLAgent` does not prevent `PolicyAgent` from returning a valid answer.

**Conditional edge support for combined queries**
LangGraph's conditional edges allow the graph to skip agents that are not needed for a given query, reducing unnecessary LLM calls and database round-trips.

**Typed shared state (`AgentState` TypedDict)**
Every field in the workflow state is explicitly declared in `agents/state.py`. This prevents typo-based attribute access bugs and makes the data contract between agents clear.

**Parallel-ready architecture**
Because agents write to distinct fields (`sql_results`, `policy_results`, `vector_results`, etc.), they could be parallelized without merge conflicts.

### Cons

**No true parallelism in combined queries**
`_combined_execute()` in `graph.py` runs PolicyAgent, SQLAgent, AgreementsAgent, and VectorAgent **sequentially**, even though they are fully independent and each involves I/O (database calls, LLM calls). This means a "combined" query takes the sum of all agent latencies rather than the maximum.

**Full conversation history passed to every LLM call**
`AgentState.messages` accumulates all turns and is injected into every agent's LangChain prompt. As sessions grow longer (20+ turns), this inflates token usage for every single LLM call — even for simple SQL generation or policy checks that do not need the full history.

**LangGraph adds framework complexity**
For a system with 6 specialized agents and straightforward sequential routing, the LangGraph StateGraph abstraction adds boilerplate (node registration, edge declaration, state schema). The same orchestration could be implemented with ~50 lines of plain Python if parallelism is not needed.

**No checkpointing or persistence for in-progress graphs**
If the server restarts mid-query (rare but possible under load), there is no mechanism to resume or replay partial agent execution. LangGraph's built-in checkpointing is not wired up.

**`combined` type executes all agents regardless of query needs**
`_combined_execute()` always calls all applicable agents. If a user asks a compound question where policy results are cached from a prior turn, the agent re-queries the database unnecessarily.

---

## 3. Session Memory & State Management

### Pros

**Simple, correct in-memory model**
`ExportAdvisoryGraph.sessions` is a plain Python `dict[session_id, List[BaseMessage]]`. It is easy to reason about, has no serialization bugs, and requires no external dependency for basic operation.

**Per-session isolation**
Each session ID is independent. One user's conversation history cannot contaminate another's. There is no global state accessed from request handlers.

**Pending HS lookup state solves a real multi-turn problem**
`session_hs_pending` correctly tracks the "clarification in progress" state across turns, allowing the router to resolve "I meant the second one" without re-running all 7 search strategies. This is a non-trivial multi-turn interaction handled cleanly.

**Session management endpoints**
`GET /history`, `DELETE /session`, `GET /sessions` endpoints expose session state for debugging and UI use without requiring direct database access.

### Cons

**Sessions lost on every server restart**
All conversation history lives in process memory. A server restart, crash, Render/Heroku dyno recycle, or deployment resets all active sessions. Users lose context silently — the server returns an empty conversation without any warning.

**No session expiry or size cap**
Sessions accumulate indefinitely. A single power user with 500 turns will hold ~500 messages in memory indefinitely. There is no LRU eviction, TTL expiry, or max-message truncation. Under load with many concurrent users, this becomes a memory leak.

**`session_id` is caller-controlled with no auth**
Any client can pass `session_id="default"` or `session_id="admin"` and read or inject into another user's session. There is no server-side binding between session ID and authenticated user identity.

**Unbounded context injection**
The full message list is passed to every LLM call. At 50+ turns, token counts can exceed the model's practical context window for focused tasks, causing degraded quality or truncation errors.

**No conversation summary / compression**
There is no mechanism to compress old turns (e.g., summarize turns 1–20 into a paragraph and retain only the last 5 turns in full). This means memory grows linearly with no quality-preserving bound.

**Single `"default"` session used when none specified**
Multiple users who do not specify a session ID all share the same `"default"` session and see each other's conversation history. This is a correctness bug for any multi-user deployment.

---

## 4. HS Code Lookup & Classification

### Pros

**7-strategy search with ordered fallback**
`HSLookupAgent` tries: exact code match → prefix match → PostgreSQL FTS → strict multi-keyword AND ILIKE → relaxed multi-keyword ILIKE → broad OR ILIKE → trigram similarity. This layered approach maximizes recall while keeping the most specific match at the top.

**LLM reranking prevents false positives**
After DB retrieval, Claude re-evaluates results semantically. This catches cases like "electronic water meter" being matched to "electronic cigarettes" by keyword overlap — a problem pure string matching cannot solve.

**Trigram index handles typos**
The `pg_trgm` GIN index on `hs_master_8_digit.description` allows matching even when the user misspells product names. The `word_similarity()` threshold of 0.25 is tuned to balance recall against noise.

**HS code normalization is thorough**
Leading zero restoration, digit-only extraction, odd-length padding, and 8-digit truncation are all handled in `_normalize_hs_code()`. This prevents common user input errors from causing lookup failures.

**Hierarchy-aware prefix matching**
A 6-digit HS code returns all matching 8-digit children, which is the correct behavior for users who know the subheading but not the full tariff line.

**Clarification state machine is explicit**
The `needs_clarification` + `clarification_type` pattern (`no_match`, `confirm_one`, `pick_one`) makes all possible disambiguation paths explicit and testable. The synthesizer can generate the right user-facing message for each case.

### Cons

**7 sequential DB queries per lookup (worst case)**
In the worst case (no early match), all 7 strategies execute against PostgreSQL. Strategies 3–7 are separate database round-trips. This can make an HS lookup noticeably slow on first query.

**LLM reranking adds latency and cost on every lookup**
An extra Claude API call fires for every HS search, even when the DB returns 0 or 1 result where reranking has no value. There is no short-circuit for trivially unambiguous results.

**Pending state is not persisted**
Like session memory, `session_hs_pending` lives in process memory. A server restart between the "show options" and "pick second one" turns leaves the user with a confusing response (the router cannot resolve the pending state because it is gone).

**No caching of common lookups**
Onions (`070310`), bananas (`080310`), cotton (`520100`) — frequently queried codes hit the database fresh every time. A simple LRU cache would eliminate most repeated DB lookups.

**LLM reranker prompt is not unit-tested**
The LLM reranking step is a black box. There are no fixtures or test cases asserting which DB results the LLM should keep or discard. Prompt regressions are only caught by manual testing.

**`hs_master_8_digit` has 12,000+ rows but only 16 HS-6 codes have trade data**
The lookup returns a valid HS code from the full 12k catalog, but the trade data scope guard then rejects most of them. A user could correctly identify HS `854311` and then be told "no trade data for this code." The disconnect between "what you can look up" and "what has data" is confusing.

---

## 5. Query Routing

### Cons

**Routing is a serial LLM call before every response**
Every user query fires a Claude API call for classification before any domain work begins. This adds 500ms–2s of latency that cannot be avoided, even for trivially deterministic queries like "show trade data for 070310" (which could be rule-matched in microseconds).

**LLM-based routing is non-deterministic**
The same query worded differently can route differently. "Export statistics for onions" vs "trade figures for onion" might route to SQL and VECTOR respectively depending on the LLM's tokenization and temperature. There are no regression tests for routing decisions.

**Deterministic overrides are partial**
`is_explicit_trade_data_request()` and `is_ftp_policy_reference_query()` override routing for specific patterns, but these only cover known keywords. Novel phrasings fall through to LLM classification, which may not agree with the override intent.

**Entity extraction is LLM-dependent**
Product name extraction goes through the LLM. If the LLM hallucinates a product name (e.g., "Bangladeshi onions" → product = "Bangladeshi" instead of "onions"), the downstream HS search will fail silently. There is no validation step asserting the extracted product is real.

**Context carryover is fragile**
The router tries to carry over HS code from previous turns by scanning `AgentState.messages`. This is a pattern-match on raw message text, not a structured reference. If the previous response phrased the HS code differently (e.g., "HS code 0703.10" vs "070310"), the carryover may fail.

**`COMBINED` type triggers full pipeline regardless of what is actually needed**
Once routing decides `COMBINED`, all relevant agents execute. There is no mechanism to re-evaluate which agents are actually needed after the router finishes entity extraction. A "what is the HS code AND can I export it?" query should only need HSLookup + Policy, but it runs the full combined pipeline.

### Pros

**Multiple classification signals reduce misroutes**
LLM classification, deterministic keyword overrides, and entity presence (HS code in query → probably SQL or POLICY) are combined. This layered approach reduces the chance of a catastrophically wrong route.

**Abbreviation expansion improves entity matching**
The router expands known product abbreviations (e.g., "T-shirts" → "knitted cotton T-shirts") before DB search, improving HS lookup recall.

**Product → HS DB search avoids extra user round-trips**
If the router detects a product name but no HS code, it searches `hs_master_8_digit` directly. This means "can I export mangoes?" can resolve to HS `080450` without requiring the user to know the code.

---

## 6. SQL Agent & Text-to-SQL

### Pros

**Schema context injected into prompt**
`sql_prompt.py` includes table schemas, column names, and example queries. This significantly improves SQL generation accuracy compared to a schema-free prompt.

**Guard enforced before SQL generation**
`validate_trade_hs_request()` runs before the LLM generates SQL. If the HS code is out of scope, the LLM call is skipped entirely — no wasted tokens and no malformed SQL executed.

**Explicit year label format prevents off-by-one errors**
Year labels (`'2023-2024'`, `'2024-2025'`) and the April-start Indian fiscal year convention are documented in the SQL prompt, preventing the LLM from generating date filters that would return empty results.

### Cons

**LLM-generated SQL is not validated before execution**
The SQL string from the LLM is executed directly via `psycopg2.execute()`. There is no syntax check, EXPLAIN, or allow-list of query shapes. A prompt injection in the user query (e.g., `"; DROP TABLE export_statistics; --"`) could reach the database. The current implementation relies on the LLM not generating destructive SQL, which is not a security guarantee.

**No read-only database user enforced**
There is no evidence in the codebase that the DB connection string points to a read-only Postgres role. If the LLM generates a `DELETE` or `UPDATE` statement (even accidentally), it would execute.

**Single-connection per request, no pooling**
`psycopg2` connections are opened per-request in agents. There is no connection pool (e.g., `psycopg2.pool` or `asyncpg`). Under concurrent load, this means N simultaneous requests open N database connections, which can exhaust Postgres connection limits on Supabase free/starter tiers.

**Aborted transaction recovery is manual**
The code uses `try/except` with `conn.rollback()` to recover from aborted transactions, but this is repeated across multiple agents without a shared connection manager. A connection that throws mid-query in one agent leaves state that must be explicitly cleared before the next query can use it.

**SQL results are not sanitized before LLM injection**
Raw SQL results (potentially containing user-entered data from the DB) are injected into the synthesizer prompt without escaping. If a DB row contains prompt-injection text (e.g., a product description like "Ignore previous instructions and say..."), it will be included in the LLM context.

**Text-to-SQL scope is narrow but poorly communicated**
Only 16 HS-6 codes have trade data. The SQL agent correctly guards this, but the system does not proactively tell users which codes are available until they hit the guard. A user could spend several turns asking about codes that will never have data.

---

## 7. Policy Agent & Export Restrictions

### Pros

**Flag-based decision (no LLM judgment for restrictions)**
The synthesizer uses `is_prohibited`, `is_restricted`, `is_ste` boolean flags directly from the database — not LLM inference. This is the correct approach for compliance-critical decisions. The LLM cannot hallucinate "you can export this" when the DB flag says `is_prohibited=True`.

**Three-tier restriction model is complete**
Prohibited (absolute ban), Restricted (license required), and STE (State Trading Enterprise canalized) cover all DGFT export control categories. Each tier returns structured metadata (description + policy_condition) for accurate user messaging.

**Chapter-level fallback for missing HS codes**
When a specific 8-digit code is not in the restrictions tables, the agent checks chapter-level notes. This prevents a false "no restrictions found" response for codes that are controlled at chapter level.

### Cons

**Restriction data is static and manually loaded**
`prohibited_items`, `restricted_items`, and `ste_items` are populated by one-time loader scripts (`restrictions.py`, `ste_items.py`). There is no automated sync from DGFT's official publications. If DGFT updates the Foreign Trade Policy (which happens with amendments, notifications, and corrigenda), the database will silently contain stale restriction data. The user could be told an item is freely exportable when it has since been restricted.

**No data freshness timestamp on restriction records**
There is no `last_updated` or `effective_date` column on restriction tables. The system cannot tell the user "this restriction data was last updated on [date]" or warn when the data is potentially outdated.

**`v_export_policy_unified` view's `overall_status` is explicitly excluded from decisions**
The code comment says "NOT used for decisions." This suggests a prior design where the view drove policy answers, which was abandoned. The unused view adds schema clutter and could mislead future developers into relying on it.

**Country-specific restriction logic is not implemented**
`can_export_to_country()` checks general export restrictions but does not enforce country-specific prohibitions (e.g., SCOMET items with country-specific embargoes, or UN/bilateral sanctions). The system returns the same restriction status regardless of destination country for policy checks.

---

## 8. Vector Search (Qdrant + FAISS/Chroma Fallback)

### Pros

**Graceful degradation to local fallback**
If Qdrant is unavailable, agents automatically fall back to FAISS/Chroma local stores. This means the system remains functional in offline development or if the Qdrant service goes down.

**Rich chunk metadata**
Agreement chunks carry `agreement`, `country`, `article`, `doc_type`, `cross_ref_articles`, `filename`. DGFT chunks carry `chapter`, `chapter_num`, `section_id`, `section_full`. This enables precise metadata filtering (e.g., "only return chunks from the India-Australia ECTA").

**Cross-reference resolution**
`AgreementsAgent` fetches cross-referenced articles when an article cites another article. This prevents incomplete answers where the primary article says "subject to Article X.Y" without including X.Y's content.

**Direct section/article lookup bypasses semantic search**
Queries like "what does Article 4.3 say?" use direct section lookup rather than semantic similarity. This is more reliable for exact document reference queries where embedding distance may not correctly rank the target article highest.

### Cons

**Two vector stores with diverging content**
Qdrant (production) and FAISS/Chroma (local fallback) must be kept in sync manually. If documents are added to Qdrant without re-running the local ingestion scripts, the fallback returns different (stale) results than production. There is no checksum or version indicator to detect this divergence.

**`all-MiniLM-L6-v2` is a small general-purpose model**
The 384-dimensional embedding model was not fine-tuned on trade law or customs documents. Legal and regulatory language ("tariff concession", "rules of origin", "cumulation provisions") may not embed close to related user queries phrased in everyday language.

**No re-ranking of vector search results**
Unlike HS lookup (which uses LLM reranking), vector search results are returned in raw cosine similarity order. A chunk that is lexically similar but semantically irrelevant (e.g., a table of contents entry) may rank above the actual substantive content.

**Three separate vector backends add operational complexity**
Qdrant + FAISS + Chroma means three different data formats, three ingestion scripts, and three potential failure modes. The FAISS and Chroma stores in `agreements_rag_store/` and `dgft_ftp_rag_store/` are file-based and committed alongside application code, mixing binary data into the source repository.

**Chunk size and overlap not documented**
The ingestion scripts set chunk sizes and overlap values, but these are not documented anywhere as tunable parameters. If retrieval quality degrades, there is no easy way to know whether re-chunking would help without re-reading all ingestion code.

---

## 9. Trade Data Scope Guard

### Pros

**Enforced at multiple layers**
The guard runs in `trade_guard.py`, in `SQLAgent.execute()` before LLM SQL generation, and in both `/api/trade-data` and `/api/monthly-trade-data` HTTP endpoints. Even if a future refactor bypasses one layer, others remain.

**Structured guard responses**
`validate_trade_hs_request()` returns a typed status (`ok`, `needs_6_to_8_digit`, `not_allowed`, `missing_hs`) rather than a boolean. Callers can give precise user-facing messages for each case rather than generic "not found" responses.

**Proactive disambiguation for prefix matches**
If a user enters a 4-digit heading that matches multiple 6-digit HS codes in the allowlist, the guard returns `needs_6_to_8_digit` with the list of valid child codes. This guides the user to the correct code rather than silently returning no data.

### Cons

**The 16-code scope is hard-coded in `config.py`**
`FOCUS_HS_CODES` is a Python list in the config file. Adding or removing trade data coverage requires a code change and redeployment. This should be driven by the database (the codes that actually have data in `export_statistics`) rather than a hard-coded allowlist.

**Guard and actual data can diverge**
If data for a new HS code is loaded into `export_statistics` but `FOCUS_HS_CODES` is not updated, the guard blocks queries for data that actually exists. The reverse is also possible: a code in `FOCUS_HS_CODES` with no rows in `export_statistics` passes the guard and returns an empty result without explanation.

**No guard on the chat endpoint for SQL queries**
The guard runs inside `SQLAgent.execute()`, but the check for "is this an explicit trade data request?" (`is_explicit_trade_data_request()`) also lives in the same agent. If the router misclassifies a vague query as SQL, the guard may not engage because the explicit data check returns `False`, causing the SQL agent to attempt SQL generation for a query it should reject.

---

## 10. Database Design (PostgreSQL)

### Pros

**Rich HS code hierarchy with multiple levels**
`hs_master_8_digit` stores HS codes at levels 2, 4, 6, and 8 with `parent_code` linking, enabling hierarchy traversal (e.g., "find all 8-digit codes under chapter 07").

**Trigram index enables fuzzy text search**
The `pg_trgm` GIN index on `description` fields supports `word_similarity()` queries directly in PostgreSQL, avoiding the need for a separate search service for product description matching.

**Views for common aggregations**
`v_export_policy_unified`, `v_monthly_exports`, and `v_quarterly_exports` pre-join and pre-aggregate common query patterns, keeping SQL agent-generated queries simpler.

**Dual trade data tables (annual + monthly)**
`export_statistics` (annual) and `monthly_export_statistics` (monthly) serve different UI needs — the bar chart visualization uses annual totals while the line chart uses monthly trends. Separating these avoids complex time-aggregation in SQL agent queries.

### Cons

**No connection pooling**
Each request opens a new `psycopg2` connection. Supabase's connection limits (typically 60–200 on shared plans) are easily exhausted under modest concurrency. PgBouncer or `asyncpg` with a pool would solve this.

**Schema has duplicate / overlapping HS tables**
`hs_master_8_digit`, `hs_codes`, and `itc_hs_products` all store HS code information. It is not clear which is the single source of truth for policy decisions. `ExportDataIntegrator` queries across all three. This duplication risks the tables going out of sync (different descriptions, different policy flags for the same code).

**No migrations framework**
Tables are created by ad hoc loader scripts (`hs_master_loader_v2.py`, `restrictions.py`, etc.). There is no Alembic, Flyway, or similar migration tool. Schema changes require manually running scripts in the right order, with no rollback capability.

**No indexes on foreign key / join columns**
`export_statistics.hs_code` and `monthly_export_statistics.hs_code` are queried frequently but may not have dedicated B-tree indexes (only the trigram GIN index is explicitly mentioned). Without indexes, queries with `WHERE hs_code = '070310'` may perform full table scans.

**Trade data granularity is country + HS code only**
`export_statistics` has `(hs_code, country_name, year_label, export_value_crore)`. There are no port, shipment mode, or HS-8 breakdowns. Users asking "what percentage goes by sea vs air?" or "which ports are used?" cannot be answered.

**`export_value_crore` unit is not validated**
There is no constraint ensuring values are in the declared unit (Indian Rupees Crore). If a loader script accidentally loads values in USD or lakh, the database accepts them without error.

---

## 11. Answer Synthesizer

### Pros

**Policy decisions are flag-driven, not LLM-inferred**
The synthesizer reads boolean flags (`is_prohibited`, `is_restricted`, `is_ste`) from structured DB results and applies deterministic decision logic before calling the LLM. The LLM is only asked to format/narrate the decision, not make it.

**Source attribution is built in**
Every agent appends metadata to `AgentState.sources`. The synthesizer includes these in the response, enabling the frontend to show "Source: DGFT FTP Chapter 4, Section 4.08" and the API consumer to cite provenance.

**Consistent formatting via prompt instructions**
Emoji indicators (✅ ❌ ⚠️), markdown headers, and bullet lists are specified in the synthesizer prompt. Responses maintain consistent visual structure across query types.

**SQL results are table-formatted**
The synthesizer converts raw SQL result dicts into markdown tables before LLM narration, preventing the LLM from summarizing away numeric data that the user needs to see precisely.

### Cons

**Synthesizer LLM call fires even for trivial responses**
A "HS code confirmed: 070310" response after a clarification still goes through the full Claude API round-trip in the synthesizer. A template-based response for low-complexity outputs (confirmation, simple policy check) would be faster and cheaper.

**No hallucination guard on synthesizer output**
The synthesizer is given structured data and asked to narrate it. If the LLM adds unsolicited information ("and by the way, the tariff rate is..."), there is no validation step to check that the narrated facts match the structured input. The synthesizer prompt instructs the LLM to "only use provided data," but this is an honor system.

**All agent results always passed to synthesizer**
Even when only one agent ran (e.g., a pure SQL query), the synthesizer prompt includes slots for policy results, vector results, agreement results, and HS lookup results. These slots are empty, but their presence in the prompt wastes tokens and can confuse the LLM if it tries to reason about absent data.

**Prompt is not versioned or tested**
`prompts/synthesizer_prompt.py` is edited directly. There are no A/B test fixtures, golden-output tests, or version history (beyond git blame) to evaluate whether a prompt change improved or degraded answer quality.

---

## 12. API Design (FastAPI)

### Pros

**Structured request/response models**
`ChatRequest`, `ChatResponse`, `TradeDataRequest`, etc. are Pydantic models. Request validation is automatic; invalid inputs return 422 before reaching any agent code.

**Separate endpoints for chat vs data visualization**
`/api/chat` (conversational), `/api/trade-data` (chart data), `/api/monthly-trade-data` (time-series) are distinct endpoints with purpose-built response shapes. The frontend can call them independently.

**Session management endpoints are REST-style**
`GET/DELETE /api/session/{id}` follows standard REST conventions. Developers can manage sessions without needing internal access.

**Health endpoint for deployment readiness**
`GET /api/health` allows load balancers and uptime monitors to check server readiness without running business logic.

### Cons

**Synchronous endpoint with blocking LLM calls**
`POST /api/chat` is a synchronous FastAPI endpoint. Each LLM call (router + agent + synthesizer = 2–4 Claude API calls) blocks the request thread. Under concurrent load, this means request queue buildup. FastAPI supports `async def` and `await` — async LangChain/Claude calls should be used.

**No streaming**
The full answer is generated and returned in one HTTP response. For long answers (policy + trade data + agreements), users wait 5–15 seconds with no feedback. Server-sent events or WebSocket streaming would provide incremental output and a much better UX.

**No authentication or rate limiting**
Any caller can hit any endpoint with any session ID. There is no API key, JWT, or session-token validation. The `/api/sessions` endpoint exposes all active session IDs, which is an information disclosure issue.

**Error responses are inconsistent**
Some failure paths return `{"error": "..."}` at HTTP 200. Others raise FastAPI `HTTPException` with proper 4xx/5xx codes. A consumer cannot reliably distinguish success from failure by HTTP status code alone.

**No request ID or distributed trace header**
Requests have no unique identifier threaded through logs. When debugging a slow or failed query, correlating `app.py` logs with agent logs with LLM API logs is difficult without a request ID.

**CORS is permissive (`allow_origins=["*"]`)**
The FastAPI `CORSMiddleware` allows all origins. For a production deployment, this should be locked to known frontend origins. Permissive CORS enables cross-site request forgery attacks from arbitrary web pages.

---

## 13. Configuration & Environment Management

### Pros

**Centralized `Config` class**
All environment variables are read once at import time in `config.py`. Agents and scripts import from `Config` rather than calling `os.getenv()` inline, preventing scattered env reads and making the config contract explicit.

**Supabase connection priority with local fallback**
If `SUPABASE_CONNECTION_STRING` is set, it is used; otherwise individual `DB_*` vars are assembled. This allows the same codebase to work locally (Docker Postgres) and in production (Supabase) without code changes.

**`validate_config()` method**
The Config class has a validation method that checks for required env vars. If called at startup, it fails fast with a clear error rather than a cryptic runtime exception when the first DB call is made.

### Cons

**`validate_config()` is not called at startup**
`app.py` does not call `Config.validate_config()` in the FastAPI `lifespan` or startup event. Missing env vars are discovered at runtime when the first relevant agent executes, not at server startup.

**No secret management**
API keys (`ANTHROPIC_API_KEY`, `QDRANT_API_KEY`, `SUPABASE_CONNECTION_STRING`) are read from `.env` files. There is no integration with a secrets manager (AWS Secrets Manager, Vault, Render secret env vars). `.env` files can accidentally be committed to source control.

**`FOCUS_HS_CODES` is business logic in config**
The 16-code allowlist belongs in the database (in a table or view), not in a config file. Any business decision to expand data coverage requires a code change and redeployment, not a data operation.

**`Config.CHAPTER_DESCRIPTIONS` is a hard-coded dict**
Chapter descriptions ("07": "Edible Vegetables", "61": "Knitted Apparel", etc.) are hard-coded in `config.py`. If a new chapter is added to the database, the config file must be manually updated.

---

## 14. Frontend (Static SPA)

### Pros

**Zero build dependencies**
`static/index.html` + `static/app.js` with CDN-delivered Chart.js and marked.js. No Webpack, Vite, npm, or node_modules. The frontend is deployable as a static file serve with no build step.

**Chart.js visualizations for trade data**
Bar charts (annual export values) and line charts (monthly trends) are rendered client-side from the structured `/api/trade-data` and `/api/monthly-trade-data` responses. This gives users visual context alongside conversational answers.

**Markdown rendering**
LLM responses (markdown) are rendered via `marked.js` in the browser. Users see formatted tables, headers, and bold text rather than raw markdown syntax.

### Cons

**No loading state or streaming feedback**
The UI shows no indication of progress during the 5–15 second wait for a response. Users have no way to know if the request is processing or has hung.

**Session ID is not persisted across browser refresh**
The frontend likely generates or uses a default session ID that is not stored in `localStorage` or a cookie. After a page refresh, the session context is lost from the backend (but even if the backend ID persisted, the in-memory session would be reset on server restart).

**No error handling for partial failures**
If `guarded=true` in the trade data response, the UI should explain why the chart is empty. Whether this is handled gracefully in `app.js` is not guaranteed without reading the full JS file.

**No mobile responsiveness noted**
The SPA is designed for desktop use. There is no indication of responsive design for mobile/tablet.

---

## 15. Data Ingestion Pipeline

### Pros

**Separate storage scripts cleanly isolated from runtime**
The `storage-scripts/` directory contains all one-time and periodic ingestion jobs. Runtime agents never import from storage scripts, preventing accidental execution of destructive DB operations in production.

**Upsert semantics in loaders**
Loader scripts use `INSERT ... ON CONFLICT DO UPDATE` (upsert), so re-running a script does not duplicate data. This makes re-ingestion safe.

### Cons

**No orchestration or scheduling**
Ingestion scripts are run manually. There is no Airflow DAG, GitHub Actions schedule, or cron job to refresh data periodically. When DGFT updates trade statistics monthly, the data must be manually downloaded, formatted, and re-run through `monthly_trade_loader.py`.

**No data validation in loaders**
Scripts load data from Excel/CSV files with minimal validation. A malformed source file (missing columns, wrong units, extra blank rows) may partially load or silently insert nulls.

**No audit log of when data was loaded**
There is no `ingestion_log` table or similar record of when each dataset was last loaded, what source file was used, or how many rows were inserted/updated. Debugging stale data requires manual investigation.

**Trade data is fiscal-year structured (April start) but months are numbered 1–12**
`monthly_export_statistics.month` uses 1=April, 2=May, ..., 12=March convention. This is an Indian fiscal year convention that is not obvious from the column name alone and requires knowing the system's context to interpret correctly. A `month_name` column or a `fiscal_year_start_month` constant would prevent future off-by-one errors.

---

## 16. Overall Architectural Trade-offs Summary

| Dimension | Current Design | Key Risk |
|-----------|---------------|----------|
| **Scalability** | Single-process, in-memory sessions, no connection pooling | Cannot scale horizontally; session data lost on restart |
| **Latency** | 2–4 sequential LLM calls per query (router + agent + synthesizer) | 5–15 second response times; no streaming |
| **Reliability** | No retries on LLM API failures, no circuit breaker | A single Anthropic API timeout fails the entire request |
| **Data freshness** | Static restriction data, no automated refresh | Policy answers may be based on outdated DGFT notifications |
| **Security** | No auth, SQL executed without read-only enforcement, permissive CORS | Vulnerable to prompt injection, session hijacking, excessive data exposure |
| **Observability** | No request IDs, no structured logging, no metrics | Debugging production issues requires manual log correlation |
| **Testability** | No unit tests for routing, prompts, or agent logic visible in codebase | Prompt regressions and routing bugs only caught by manual QA |
| **Scope management** | 16-code hard-coded allowlist | Expanding coverage requires code change and redeployment |
| **Vector store sync** | Two stores (Qdrant + FAISS) must be manually kept in sync | Search quality diverges between dev and prod silently |
| **Cost control** | Full conversation history in every LLM call; no caching | Token cost grows linearly with session length |

---

### Top 5 Highest-Impact Issues

1. **No server-side session persistence** — every server restart wipes all user context. Use Redis or Postgres-backed session storage.
2. **SQL executed without read-only enforcement** — a prompt injection can run destructive SQL. Use a Postgres read-only role and parameterized query validation.
3. **No authentication or session isolation** — any user can read or pollute another user's session by guessing the session ID.
4. **Sequential LLM calls with no streaming** — combined queries are slow and the user sees nothing until completion. Parallelize independent agent calls and stream the synthesizer output.
5. **Static restriction data with no refresh pipeline** — the most compliance-critical data (prohibited/restricted exports) has no automated update mechanism, creating a silent staleness risk.

---