# LangGraph System Guide

This document reflects the current implementation in `agents/` and `app.py`.

## 1) Graph topology

Implemented in `agents/graph.py` with `StateGraph(AgentState)`.

```text
Entry: router

router -> sql         -> synthesizer -> END
router -> policy      -> synthesizer -> END
router -> agreements  -> synthesizer -> END
router -> vector      -> synthesizer -> END
router -> hs_lookup   -> synthesizer -> END
router -> combined    -> synthesizer -> END
router -> general     -> synthesizer -> END
```

### Node registration

- `router`: `QueryRouter.route`
- `sql`: `SQLAgent.execute`
- `policy`: `PolicyAgent.execute`
- `agreements`: `AgreementsAgent.execute`
- `vector`: `VectorAgent.execute`
- `hs_lookup`: `HSLookupAgent.execute`
- `combined`: `ExportAdvisoryGraph._combined_execute`
- `synthesizer`: `AnswerSynthesizer.execute`

## 2) AgentState contract

Defined in `agents/state.py`.

Key fields:

- `messages`: full conversation history (LangChain messages)
- `user_query`: current turn
- `query_type`: `sql|policy|agreements|vector|hs_lookup|combined|general`
- `hs_code`, `country`, `product_name`
- `sql_results`, `policy_results`, `agreement_results`, `vector_results`, `hs_lookup_results`
- `needs_clarification` (HS disambiguation)
- `sources` (trace metadata)
- `next_agent`
- `final_answer`

## 3) Router behavior (`agents/router.py`)

### 3.1 LLM + deterministic controls

Router first uses prompt classification (`prompts/router_prompt.py`) then applies deterministic overrides:

1. **DGFT FTP reference override**
   - If query looks like FTP article/section reference (example `Article 8.04`) and is not explicit trade-data intent:
   - force route to `vector`
   - clear product/HS carry-over for that turn

2. **HS extraction**
   - regex extraction for 6–8 digit HS
   - normalization of dropped leading zeros

3. **Context carry-over**
   - if HS not present, may reuse recent HS from session history
   - suppressed for new product lookup intent and FTP article/reference queries

4. **Product-to-HS lookup**
   - uses HS lookup search pipeline when product name is detected
   - stores candidate list in `hs_lookup_results` when available

5. **Combined auto-upgrade**
   - `policy/sql` + detected HS+country -> `combined`
   - policy-style follow-up keywords after HS lookup can upgrade to `combined`

## 4) Trade guard (`agents/trade_guard.py`)

Centralized rules used by router/graph/sql/api layers.

### 4.1 Explicit trade-intent detection

`is_explicit_trade_data_request(query)` checks terms/patterns like:

- `trade data`, `export statistics`, `monthly exports`, `quarterly`, `ytd`, etc.

### 4.2 FTP policy-reference detection

`is_ftp_policy_reference_query(query)` recognizes DGFT/FTP/HBP + article/section patterns to avoid HS/trade misrouting.

### 4.3 HS scope validation for trade data

`validate_trade_hs_request(...)` enforces allowlist behavior:

- `ok`: valid 6–8 digit HS mapping to allowed HS-6
- `needs_6_to_8_digit`: short prefix matches tracked HS, ask for full 6–8 digits
- `not_allowed`: HS outside tracked trade scope
- `missing_hs`: no usable HS provided

## 5) SQL agent behavior (`agents/sql_agent.py`)

### 5.1 Guarded trade requests

When a query is explicitly trade-data intent:

- validates HS scope through `validate_trade_hs_request`
- on invalid scope, returns successful guarded result (no SQL execution)
- emits source record `type: trade_data_guard`

### 5.2 Non-trade SQL queries

For non-trade SQL intents (for example, policy listing queries), SQL generation/execution proceeds normally.

## 6) Combined behavior (`agents/graph.py`)

`_combined_execute` is sequential and conditional:

1. **SQL only if explicit trade-data request**
2. **Policy check**
   - HS available: direct policy agent check
   - no HS: chapter-level fallback queries (`prohibited_items`, `restricted_items`, `ste_items`, `itc_chapter_policies`)
3. **Agreements search** if country exists and retriever is available
4. **DGFT FTP retrieval supplement** if retriever exists
5. route to synthesizer

This avoids accidental trade-data output for pure policy/document questions.

## 7) Retriever backends

### AgreementsAgent (`agents/agreements_agent.py`)

- backend preference: `agreements_retriever_qdrant` (Qdrant + FastEmbed)
- fallback: local `agreements_retriever` (FAISS/Chroma)
- supports direct article lookup (`Article X.Y`) and cross-reference enrichment

### VectorAgent (`agents/vector_agent.py`)

- DGFT backend preference: `dgft_ftp_retriever_qdrant`
- fallback: local `dgft_ftp_retriever`
- supports direct section lookup (`7.02`) and chapter-filtered retrieval
- may also include agreements retriever output through integrator

## 8) Synthesizer behavior (`agents/synthesizer.py`)

- Consolidates only invoked agent outputs.
- Uses explicit `NOT CHECKED` markers to avoid hallucinating missing checks.
- Handles HS-lookup clarification modes (`no_match`, `confirm_one`, `pick_one`, `too_broad`).

## 9) Session memory model

Implemented in `ExportAdvisoryGraph.sessions`:

- each `session_id` stores ordered `HumanMessage`/`AIMessage` history
- on every query:
  1) append user message
  2) invoke graph with full session messages
  3) append final assistant message

API helpers:

- `clear_session(session_id)`
- `get_session_history(session_id)`
- `list_sessions()`
- `get_session_message_count(session_id)`

## 10) Typical execution traces

### A) `Explain DGFT FTP Article 8.04`

- router deterministic override -> `vector`
- vector retrieves DGFT FTP section content
- synthesizer returns policy-text answer
- no trade-data SQL

### B) `Show trade data for chapter 08`

- explicit trade intent detected
- trade guard -> `needs_6_to_8_digit`
- SQL and API layers return guarded clarification

### C) `Can I export HS 070310 to Australia?`

- route upgraded to `combined`
- combined runs policy + agreements + DGFT FTP
- SQL runs only if trade-data intent is explicit in wording

## 11) Extension points

- Routing prompt: `prompts/router_prompt.py`
- SQL generation prompt/schema: `prompts/sql_prompt.py`, `prompts/sql_schema.py`
- Synthesis behavior: `prompts/synthesizer_prompt.py`
- New node integration: `agents/graph.py` (`add_node`, edges, route mapping)
- Guard policy adjustments: `agents/trade_guard.py`

---

Last updated: 2026-03-19