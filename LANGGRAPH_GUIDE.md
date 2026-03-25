# LangGraph System Guide

Exact implementation reference for `agents/` and `app.py`. Read alongside the code; the code is authoritative.

---

## 1. Graph topology (`agents/graph.py`)

Built with `StateGraph(AgentState)`.

```
START
  └─► router
        ├─► sql          ─► synthesizer ─► END
        ├─► policy       ─► synthesizer ─► END
        ├─► vector       ─► synthesizer ─► END
        ├─► agreements   ─► synthesizer ─► END
        ├─► hs_lookup    ─► synthesizer ─► END
        ├─► combined     ─► synthesizer ─► END
        └─► general (no agent node)
                         ─► synthesizer ─► END
```

The `"general"` route maps directly to `synthesizer` in the conditional edge map — no intermediate agent runs.

### Node registrations

| LangGraph node | Method |
|---|---|
| `router` | `QueryRouter.route` |
| `sql` | `SQLAgent.execute` |
| `policy` | `PolicyAgent.execute` |
| `vector` | `VectorAgent.execute` |
| `agreements` | `AgreementsAgent.execute` |
| `hs_lookup` | `HSLookupAgent.execute` |
| `combined` | `ExportAdvisoryGraph._combined_execute` |
| `synthesizer` | `AnswerSynthesizer.execute` |

---

## 2. AgentState contract (`agents/state.py`)

`AgentState` is a `TypedDict`. All fields flow through every node.

| Field | Type | Purpose |
|---|---|---|
| `messages` | `Sequence[BaseMessage]` (append-only) | Full session conversation history passed to every LLM call |
| `user_query` | `str` | Current user turn text |
| `query_type` | `str` | Route: `sql \| policy \| vector \| agreements \| hs_lookup \| combined \| general` |
| `hs_code` | `Optional[str]` | Normalized HS code extracted by router (digits only, leading zeros restored) |
| `country` | `Optional[str]` | Matched target country: `australia \| uae \| uk` |
| `product_name` | `Optional[str]` | Product name extracted by LLM router for description-based HS lookup |
| `sql_results` | `Optional[Dict]` | `{query, result: {columns, rows} or {affected_rows}, success, guarded?, guard_status?}` |
| `policy_results` | `Optional[Dict]` | `{result: <integrator output or chapter batch>, success}` |
| `vector_results` | `Optional[List[Dict]]` | DGFT FTP + agreements docs: `{type, text, metadata, score}` |
| `agreement_results` | `Optional[List[Dict]]` | FTA docs: `{agreement, country, article, doc_type, score, text, cross_ref_articles, is_cross_ref}` |
| `hs_lookup_results` | `Optional[Dict]` | `{results: [...], count, search_term, is_ambiguous, needs_clarification, clarification_type, clarification_message, success}` |
| `needs_clarification` | `Optional[bool]` | Propagated from `hs_lookup_results` for caller detection |
| `final_answer` | `Optional[str]` | Markdown string produced by synthesizer |
| `sources` | `List[Dict]` | Trace records appended by each agent |
| `next_agent` | `Optional[str]` | Used by conditional edges to pick next node |

### Source record types written by agents

| `type` | Written by | Key fields |
|---|---|---|
| `sql` | SQLAgent | `query`, `database`, `timestamp` |
| `policy_check` | PolicyAgent, combined | `hs_code` or `chapters`, `country`, `tables`, `timestamp` |
| `trade_data_guard` | SQLAgent | `status`, `message`, `timestamp` |
| `vector_search` | VectorAgent, combined | `store`, `num_results`, `dgft_ftp_results`, `agreement_results`, `query`, `timestamp` |
| `trade_agreements` | AgreementsAgent | `store`, `num_results`, `countries`, `agreements`, `cross_refs_included`, `timestamp` |

---

## 3. Router behavior (`agents/router.py`)

### 3.1 Step-by-step routing logic

```
1. LLM classifies query_type (prompts/router_prompt.py)
   → SQL | POLICY | AGREEMENTS | VECTOR | HS_LOOKUP | COMBINED | GENERAL
   Also extracts: PRODUCT: <name>

2. Deterministic DGFT FTP override
   IF is_ftp_policy_reference_query(query) AND NOT is_explicit_trade_data_request(query):
     query_type = "vector"
     product_name = None   ← suppress HS carry-over for FTP article lookups

3. HS code extraction (regex)
   \b(\d{6,8})\b  → normalize → restore dropped leading zeros (odd-digit lengths)

4. Context carry-over (conversation history)
   IF no HS in current query AND NOT new product query:
     scan recent messages for last HS code mentioned
   Suppressed when: query_type=hs_lookup, product_name is set, FTP reference query

5. Product-to-HS lookup (description search)
   IF no HS found AND product_name is set:
     hs_code = _find_hs_code_by_description(product_name)
     → merges policy table hits (ste_items, restricted_items, prohibited_items) + hs_master_8_digit
     → policy table hits ranked first
     IF top match came from a policy table OR query_type in (general, vector, hs_lookup):
       query_type = "policy"   ← ensures policy agent always checks known restricted items

6. Auto-upgrade to combined
   IF query_type != "hs_lookup":
     IF hs_code AND country:   query_type = "combined"
     IF hs_code AND query_type == "policy":  query_type = "combined"

7. Policy-followup keyword upgrade
   IF hs_code AND query_type in (hs_lookup, general):
     IF any keyword in query (restriction/prohibited/policy/ste/duty/etc.):
       query_type = "combined"

8. Write to state: query_type, hs_code, country, product_name, next_agent
   Store _last_hs_matches in state["hs_lookup_results"] if description search ran
```

### 3.2 HS code normalization

Strips non-digits, restores leading zero when length is odd (1→2, 3→4, 5→6, 7→8), truncates to 8 digits.

### 3.3 Description-to-HS search (`_find_hs_code_by_description`)

1. `HSLookupAgent.search_by_description(product_name, limit=20)` — searches `hs_master_8_digit`
2. `_search_policy_tables_by_description(query, limit=20)` — FTS on `restricted_items`, `prohibited_items`, `ste_items`; ILIKE fallback if FTS returns nothing
3. Merges both; policy hits ranked first; returns `merged[0]["hs_code"]` and stores full `_last_hs_matches`

---

## 4. Trade guard (`agents/trade_guard.py`)

### 4.1 Explicit trade intent detection

`is_explicit_trade_data_request(query)` returns True if query contains:
- Literal terms: `trade data`, `export statistics`, `monthly exports`, `ytd exports`, `export value`, etc.
- Pattern: `(export|trade) ... (data|stats|value|monthly|quarterly|growth|ytd|historical)`
- Reverse pattern: `(data|stats|value|...) ... (export|trade)`
- How-much pattern: `(how much|total|show|compare|...) ... (export|trade)` + data/stats/value/etc.

### 4.2 FTP policy reference detection

`is_ftp_policy_reference_query(query)` requires both:
- A DGFT/FTP context term: `dgft`, `foreign trade policy`, `ftp`, `handbook of procedures`, `hbp`
- An article/section reference: `article`, `section`, `clause`, `paragraph`, or `\d+\.\d{2,}`

### 4.3 HS scope validation

`validate_trade_hs_request(query, state_hs_code, allowed_hs6)` returns a `TradeValidationResult`:

| `status` | Condition |
|---|---|
| `ok` | Token ≥6 digits, HS-6 prefix in allowlist |
| `not_allowed` | Token ≥6 digits, HS-6 not in allowlist |
| `needs_6_to_8_digit` | Token <6 digits, prefix matches allowed code(s) |
| `missing_hs` | No usable token found; falls back to session `state_hs_code` if valid |

---

## 5. SQL Agent (`agents/sql_agent.py`)

```
1. IF is_explicit_trade_data_request(user_query):
     run validate_trade_hs_request()
     IF status != "ok":
       write guarded result to state["sql_results"]
       append trade_data_guard source record
       state["next_agent"] = "synthesizer"
       return   ← short-circuit, no SQL executed
     ELSE:
       inject "Use HS code {hs6} for trade data tables." into query_for_sql

2. Generate SQL:
   (sql_prompt | llm | StrOutputParser()).invoke({messages, query_for_sql})
   Strip markdown fences (```sql ... ```)

3. Execute via psycopg2:
   cursor.execute(sql_query)
   IF cursor.description: fetch columns + rows (capped display at 50)
   ELSE: return affected_rows

4. Write to state["sql_results"]: {query, result, success: True}
   Append sql source record
```

The SQL prompt (`prompts/sql_prompt.py`) receives the full database schema context from `prompts/sql_schema.py`.

---

## 6. Policy Agent (`agents/policy_agent.py`)

```
IF state["hs_code"] is None:
  return error result → synthesizer

IF state["country"] is set:
  result = integrator.can_export_to_country(hs_code, country, check_agreements=False)
  → returns {can_export, hs_info: {is_prohibited, is_restricted, is_ste, ...}, issues, warnings}
ELSE:
  result = integrator.get_hs_code_info(hs_code)
  → returns {is_prohibited, is_restricted, is_ste, prohibited_info?, restricted_info?, ste_info?,
             itc_policy?, chapter_notes?, description, hierarchy}

Write to state["policy_results"]: {result, success: True}
```

### ExportDataIntegrator check sequence (`export_data_integrator.py`)

For `get_hs_code_info(hs_code)`:

1. `_get_hs_code_basic(hs_code)` — `hs_codes` table, exact match first
2. `_get_itc_policy(hs_code)` — `itc_hs_products` table
3. `_check_prohibited(hs_code)` — `prohibited_items`, exact match then prefix LIKE
4. `_check_restricted(hs_code)` — `restricted_items`, exact match then prefix LIKE
5. `_check_ste(hs_code)` — `ste_items`, exact match then prefix LIKE (6-digit → 8-digit children)
6. `_get_chapter_notes(hs_code)` — `itc_chapter_notes` grouped by `note_type`

---

## 7. Combined execute (`agents/graph.py _combined_execute`)

```python
# Step 1 — SQL (conditional)
if is_explicit_trade_data_request(state["user_query"]):
    state = self.sql_agent.execute(state)

# Step 2 — Policy
if state["hs_code"]:
    state = self.policy_agent.execute(state)
else:
    # Chapter-level batch: extract chapter numbers from query
    # For each chapter: query prohibited_items, restricted_items,
    #   ste_items, itc_chapter_policies WHERE hs_code LIKE '{ch}%'
    # Write batch result to state["policy_results"]

# Step 3 — Agreements (conditional)
if state["country"] and self.agreements_agent.retriever:
    state = self.agreements_agent.execute(state)

# Step 4 — DGFT FTP vector (always if retriever available)
if self.vector_agent.dgft_retriever:
    hits = self.vector_agent.dgft_retriever.search(query, top_k=3)
    # Append to state["vector_results"] as type="dgft_ftp" entries

state["next_agent"] = "synthesizer"
```

---

## 8. HS Lookup Agent (`agents/hs_lookup_agent.py`)

Seven-strategy search against `hs_master_8_digit`, applied in order until results found:

| Strategy | Method |
|---|---|
| 1 | Exact HS code match |
| 2 | Prefix match (e.g. 6-digit matches 8-digit children) |
| 3 | PostgreSQL FTS: `plainto_tsquery('english', ...)` with min rank 0.03 |
| 4 | Top-3 longest keywords — `AND ILIKE '%kw%'` on all three |
| 5 | All extracted keywords — `AND ILIKE '%kw%'` |
| 6 | Top-5 longest keywords — `OR ILIKE '%kw%'` |
| 7 | `pg_trgm word_similarity` with threshold 0.25 |

Result handling:

| Count | `clarification_type` | `needs_clarification` | Action |
|---|---|---|---|
| 0 | `no_match` | True | Ask user for more detail |
| 1 (confident) | None | False | Return directly, no clarification |
| 2–8 | `pick_one` | True | Show table of options, ask user to pick |
| >8 | `too_broad` | True | Show top-5 sample, ask for more specific description |

Special case `confirm_one`: single result with moderate confidence — synthesizer asks user to confirm before giving policy advice.

---

## 9. Agreements Agent (`agents/agreements_agent.py`)

```
Retriever preference: agreements_retriever_qdrant → agreements_retriever (FAISS/Chroma)

1. Detect direct article reference pattern (e.g. "Article 4.3")
   IF match: direct article lookup from index → fetch that article text
   ELSE: semantic search (top 8 results)

2. Cross-reference enrichment:
   FOR each returned article WITH cross_ref_articles field:
     fetch referenced articles and append

3. Filter to requested country if set
4. Write to state["agreement_results"]
5. Append trade_agreements source record
```

---

## 10. Vector Agent (`agents/vector_agent.py`)

```
DGFT retriever preference: dgft_ftp_retriever_qdrant → dgft_ftp_retriever (FAISS/Chroma)

1. Detect direct section reference (e.g. "7.02")
   IF match: direct section lookup from section index
   ELSE: semantic search; chapter-filtered if chapter detected in query

2. Optionally supplement with agreements retriever output
   (integrator.search_trade_agreements if available)

3. Combine into state["vector_results"] as list of
   {type: "dgft_ftp", text, metadata, score}

4. Append vector_search source record
```

---

## 11. Synthesizer (`agents/synthesizer.py`)

The synthesizer never invents policy status. It builds summaries from state fields and passes them to a final LLM call.

### Policy summary construction (no LLM involved)

```python
# Path A: can_export_to_country result (has "can_export" key)
is_prohibited = result["hs_info"]["is_prohibited"]
is_restricted  = result["hs_info"]["is_restricted"]
is_ste         = result["hs_info"]["is_ste"]
# Also formats: can_export, issues, warnings, requirements

# Path B: get_hs_code_info result (no "can_export" key)
is_prohibited = result["is_prohibited"]
is_restricted  = result["is_restricted"]
is_ste         = result["is_ste"]

# Decision (same for both paths):
if not is_prohibited and not is_restricted and not is_ste:
    → "Export Policy: FREE — not found in prohibited, restricted, or STE lists."
if is_prohibited:
    → "PROHIBITED: {description} — {policy_condition}"
if is_restricted:
    → "RESTRICTED: {description} — {policy_condition}"
if is_ste:
    → "STE: Export only via {authorized_entity} — {policy_condition}"

# Chapter notes appended if present (main_notes, export_licensing, policy_conditions)
```

### HS lookup clarification formatting

- `no_match` → plain message + clarification prompt
- `pick_one` / `confirm_one` → markdown table of options
- `too_broad` → top-5 sample table + narrowing prompt
- Clean match → summary of top matches

### NOT CHECKED markers

Each summary variable starts as `"NOT CHECKED — <agent> was not invoked for this query."` and is replaced only if the agent ran. This prevents the final LLM from hallucinating results for agents that didn't run.

---

## 12. Session memory model (`agents/graph.py`)

```python
self.sessions: Dict[str, List[BaseMessage]] = {}

# On each query():
sessions[session_id].append(HumanMessage(content=user_query))
initial_state["messages"] = list(sessions[session_id])  # full history
result = graph.invoke(initial_state)
sessions[session_id].append(AIMessage(content=result["final_answer"]))
```

Every LLM call (router, SQL, synthesizer) receives the full `messages` list via `MessagesPlaceholder`. This enables contextual reference resolution ("same code", "what about UAE?", "it").

Session management API:
- `clear_session(session_id)`
- `get_session_history(session_id)` → `[{role, content}]`
- `list_sessions()`
- `get_session_message_count(session_id)`

---

## 13. LLM configuration

- Provider: Anthropic Claude via `langchain_anthropic.ChatAnthropic`
- Model: `Config.LLM_MODEL` (default `claude-sonnet-4-20250514`, env var `LLM_MODEL`)
- Temperature: `Config.LLM_TEMPERATURE` (default `0.1`, env var `LLM_TEMPERATURE`)
- Used by: `QueryRouter`, `SQLAgent`, `AnswerSynthesizer`
- NOT used by: `PolicyAgent`, `AgreementsAgent`, `VectorAgent`, `HSLookupAgent` (all DB/retriever based)

---

## 14. Execution trace examples

### A) "Explain DGFT FTP Article 8.04"

```
router: is_ftp_policy_reference_query=True → override to "vector", hs_code=None
vector: direct section lookup → returns DGFT FTP section 8.04 text
synthesizer: vector_results formatted, policy/sql = NOT CHECKED
```

### B) "Show trade data for chapter 08"

```
router: is_explicit_trade_data_request=True, hs_code extracted as "08" (2 digits)
sql_agent: validate_trade_hs_request → status="needs_6_to_8_digit"
  → guarded result, no SQL executed
synthesizer: guard message passed through
```

### C) "Can I export HS 070310 to Australia?"

```
router: hs_code="070310", country="australia"
  → auto-upgrade: hs_code + country + policy → "combined"
combined:
  1. is_explicit_trade_data_request=False → skip SQL
  2. policy_agent: can_export_to_country("070310", "australia")
  3. agreements_agent: Qdrant search for Australia FTA content
  4. dgft_ftp search: top-3 DGFT sections
synthesizer: assembles policy flags + agreement articles + DGFT text
```

### D) "Iron ore fines export rules"

```
router: LLM classifies "hs_lookup" or "policy"
  product_name="iron ore fines"
  _find_hs_code_by_description → hits ste_items table (26011131 etc.)
  top match source="ste_items" → query_type forced to "policy"
  auto-upgrade: hs_code + policy → "combined"
combined:
  policy_agent: get_hs_code_info("26011131") → is_ste=True
synthesizer: "STE: Export only via MOIL — Subject to Policy Condition 1"
```

### E) "What are the textiles rules of origin under India-UAE CEPA?"

```
router: country="uae", no HS code, LLM → "agreements"
agreements_agent: semantic search → FTA articles on rules of origin
synthesizer: cites specific articles from India-UAE CEPA
```

---

## 15. Extension points

| What to change | Where |
|---|---|
| Route classification rules | `prompts/router_prompt.py` |
| SQL generation + schema | `prompts/sql_prompt.py`, `prompts/sql_schema.py` |
| Final answer synthesis style | `prompts/synthesizer_prompt.py` |
| New graph node | `agents/graph.py`: `add_node`, `add_edge`, update conditional edge map |
| Trade-data allowlist | `config.py: Config.FOCUS_HS_CODES` |
| Trade intent patterns | `agents/trade_guard.py: _TRADE_TERMS, _TRADE_PATTERN` |
| Retriever backend switch | `agents/agreements_agent.py`, `agents/vector_agent.py` constructor |

---

Last updated: 2026-03-24
