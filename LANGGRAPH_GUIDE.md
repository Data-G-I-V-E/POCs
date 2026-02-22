# 🤖 LangGraph Multi-Agent Export Advisory System

## Overview

A sophisticated multi-agent system using **LangGraph** that intelligently routes queries to specialized agents, maintains **conversation memory** per session, and provides comprehensive answers with proper source attribution.

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      USER QUERY                              │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   QUERY ROUTER                               │
│  Analyzes query and determines appropriate agent(s)         │
│  - Extracts HS code, country                                │
│  - Routes to: SQL/POLICY/AGREEMENTS/VECTOR/COMBINED/GENERAL │
└───┬────────┬────────┬──────────┬──────────┬─────────────────┘
    │        │        │          │          │
    ▼        ▼        ▼          ▼          ▼
┌───────┐┌──────┐┌──────────┐┌──────┐┌────────────────────┐
│ SQL   ││POLICY││AGREEMENTS││VECTOR││  COMBINED AGENT    │
│ AGENT ││AGENT ││AGENT     ││AGENT ││                    │
│       ││      ││          ││      ││ 1. Runs SQL Agent  │
│Text→  ││Check:││Search:   ││Search││ 2. Runs Policy     │
│SQL    ││Proh. ││FTA text  ││DGFT  ││    Agent           │
│Query  ││Rest. ││Rules of  ││Policy││ 3. Runs Agreements │
│       ││STE   ││Origin    ││      ││    Agent (if       │
│       ││      ││Tariffs   ││      ││    country found)  │
│       ││      ││Cross-refs││      ││ 4. Feeds all to    │
│       ││      ││          ││      ││    synthesizer     │
└───┬───┘└──┬───┘└────┬─────┘└──┬───┘└────────┬───────────┘
    │       │         │         │             │
    └───────┴─────────┴────┬────┴─────────────┘
                           │
                           ▼
           ┌───────────────────────────────┐
           │    ANSWER SYNTHESIZER         │
           │  Combines all agent results   │
           │  Generates markdown answer    │
           │  with source & article cites  │
           └───────────────┬───────────────┘
                           │
                           ▼
           ┌───────────────────────────────┐
           │    FINAL RESPONSE             │
           │  - Direct Answer              │
           │  - Supporting Details         │
           │  - Source Citations           │
           │  - Agreement Article Refs     │
           └───────────────────────────────┘
```

## 🎯 Agents

### 1. **Query Router** (`agents/router.py`)
- Analyzes user intent
- Extracts entities (HS codes, countries)
- Routes to appropriate specialist agents
- Powered by Gemini 2.5 Flash
- Prompt defined in `prompts/router_prompt.py`

### 2. **SQL Agent** (`agents/sql_agent.py`) — Text-to-SQL
Handles queries requiring database operations:
- Export statistics and trade data (annual + monthly)
- Monthly trends, seasonal patterns, quarter comparisons
- Aggregations and summaries
- Historical trends
- Chapter-level analysis

**Example Queries:**
- "What is the total export value for chapter 07?"
- "Show export statistics for HS 610910 to UAE"
- "How many HS codes are restricted?"
- "What were the monthly exports of HS 610910 to UAE in 2024?"
- "Which month had the highest exports for chapter 85 to Australia?"
- "Show quarterly export trend for textiles to UK"

**Data Sources:**
- Unified SQL views (`v_export_policy_unified`, `v_monthly_exports`)
- Schema context from `prompts/sql_schema.py`
- SQL generation prompt from `prompts/sql_prompt.py`
- `export_statistics` (annual data)
- `monthly_export_statistics` (monthly 2024 data)
- `v_monthly_exports` (monthly with names)
- `v_quarterly_exports` (quarterly aggregations)
- `mv_hs_export_summary`
- Database functions

### 3. **Policy Agent** (`agents/policy_agent.py`)
Checks export feasibility and restrictions:
- Prohibited items
- Restricted items
- STE requirements
- ITC notifications
- Compliance checks

**Example Queries:**
- "Can I export HS 070310 to Australia?"
- "Is HS 850440 restricted?"
- "What are the requirements for exporting onions?"

**Data Sources:**
- `v_export_policy_unified`
- `prohibited_items`
- `restricted_items`
- `ste_items`

### 4. **Vector Agent** (`agents/vector_agent.py`)
Semantic search across DGFT policy documents:
- Foreign Trade Policy
- DGFT notifications
- Export promotion schemes

**Example Queries:**
- "DGFT policy for agricultural exports"
- "What export promotion schemes are available?"

**Data Sources:**
- ChromaDB (`dgft_chroma_db/`)

### 5. **Agreements Agent** (`agents/agreements_agent.py`) (NEW)
Searches trade agreement PDFs with article-level precision and cross-reference resolution:
- Rules of origin (Chapter 4 of most FTAs)
- Tariff commitments and duty elimination schedules
- Customs procedures and facilitation
- SPS/TBT measures
- Dispute settlement provisions
- Certificate of origin requirements

**Key Features:**
- **Article-aware chunking**: Returns whole Article sections, not arbitrary text windows
- **Cross-reference resolution**: If Article 4.3 mentions Article 4.6, both are returned
- **Country filtering**: Search only Australia, UAE, or UK agreements
- **OCR cleanup**: Fixes 15+ common scanning errors from UAE PDFs

**Example Queries:**
- "What are the rules of origin for exporting textiles to Australia?"
- "What tariff benefits does the India-UAE CEPA provide?"
- "What does Article 4.3 of the India-Australia agreement say?" 
- "Customs procedures under the India-UK FTA"
- "Certificate of origin requirements for UK exports"

**Data Sources:**
- FAISS index (`agreements_rag_store/agreements.index`)
- ChromaDB (`agreements_rag_store/agreements_chroma/`)
- Article cross-reference index (`agreements_rag_store/article_index.json`)

**Covers 3 Agreements:**
- India-Australia ECTA (AI-ECTA): 577 chunks, 190 articles
- India-UAE CEPA: 751 chunks, 249 articles
- India-UK CETA: 1,196 chunks, 449 articles

### 6. **Combined Agent** (`agents/graph.py` → `_combined_execute` method)
Handles complex queries requiring BOTH data aggregation AND policy checks AND agreement lookup:
- Runs SQL Agent first for data/statistics
- Then runs Policy Agent for chapter-level restriction checks
- Then runs Agreements Agent if a country is specified in the query
- Queries `prohibited_items`, `restricted_items`, `ste_items`, `itc_chapter_policies`
- Extracts chapter numbers from the query and does batch lookups

**Example Queries:**
- "Can I export vegetables to Australia and what are the tariff benefits?"
- "Show export values AND restrictions AND agreement provisions for chapter 07"
- "What are the export values and trade agreement benefits for textiles to UAE?"

**Why Combined?**
- Single-agent queries (SQL or Policy alone) miss data from the other
- SQL Agent can generate aggregate queries but doesn’t check restriction tables deeply
- Policy Agent checks restrictions but has no access to export statistics
- Agreements Agent searches FTA text but has no export statistics or policy data
- Combined runs all three, giving the synthesizer a complete picture

### 7. **Answer Synthesizer** (`agents/synthesizer.py`)
- Combines results from all agents
- Generates coherent response with markdown formatting
- Cites specific trade agreement articles (e.g., "Article 4.3 of AI-ECTA")
- Provides source citations
- Uses conversation history for context
- Prompt defined in `prompts/synthesizer_prompt.py`

## 🚀 Usage

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# OR install specific packages
pip install langgraph langchain-google-genai langchain-community
```

### Setup

1. Ensure `.env` file has `GOOGLE_API_KEY`:
```bash
GOOGLE_API_KEY=your_api_key_here
```

2. Database must be set up (run `database_unification.py` first)

### Basic Usage

```python
from agents import ExportAdvisoryGraph

# Initialize
graph = ExportAdvisoryGraph()

# Ask a question
result = graph.query("Can I export HS 070310 to Australia?")

# Print formatted response
print(graph.format_response(result))
```

### Interactive Mode

```bash
python -m agents.graph
```

### Quick Test

```bash
python test_agreement_queries.py --quick
```

## 📦 Code Structure

The system is organized into two packages:

- **`agents/`** — One file per agent, plus `state.py` (shared `AgentState`) and `graph.py` (orchestrator)
- **`prompts/`** — All LLM prompts as editable Python string constants

Import from either path:
```python
from agents import ExportAdvisoryGraph          # Preferred
from langgraph_export_agent import ExportAdvisoryGraph  # Backward compat
```

## 📊 Example Queries

### SQL Agent Queries

```python
# Aggregation
graph.query("What is the total export value for chapter 07?")

# Statistics
graph.query("Show export statistics for HS 610910")

# Comparison
graph.query("Compare exports of textiles to all three countries")

# Trends
graph.query("What's the growth rate for HS 070310 exports?")

# Monthly data
graph.query("What were the monthly exports of HS 610910 to UAE in 2024?")

# Best month
graph.query("Which month had the highest exports for chapter 85 to Australia?")

# Quarterly
graph.query("Show quarterly export trend for textiles to UK in 2024")
```

### Policy Agent Queries

```python
# Export check
graph.query("Can I export HS 070310 to Australia?")

# Restrictions
graph.query("Is HS 850440 prohibited or restricted?")

# Requirements
graph.query("What are STE requirements for chapter 26?")

# Status check
graph.query("Check export status for HS 620342")
```

### Vector Agent Queries

```python
# Agreements
graph.query("What are the tariff rates in the Australia agreement?")

# Rules
graph.query("Rules of origin requirements for UAE")

# Certificates
graph.query("What certificates are needed for UK exports?")

# Policies
graph.query("DGFT policy for agricultural exports")
```

## 📝 Response Format

Each response includes:

```python
{
    "answer": "Comprehensive answer...",
    "sources": [
        {
            "type": "sql",
            "query": "SELECT ...",
            "database": "PPL-AI",
            "timestamp": "2026-02-07T..."
        },
        {
            "type": "policy_check",
            "hs_code": "070310",
            "country": "australia",
            "tables": ["v_export_policy_unified", ...],
            "timestamp": "2026-02-07T..."
        }
    ],
    "query_type": "policy",
    "hs_code": "070310",
    "country": "australia",
    "timestamp": "2026-02-07T..."
}
```

## 🔍 Query Routing Logic

The router uses LLM-based classification:

| Query Contains | Routed To | Examples |
|---------------|-----------|----------|
| "how many", "total", "statistics" | SQL Agent | "What is total export value?" |
| "monthly", "trend", "quarterly", "best month" | SQL Agent | "Monthly exports of textiles to UAE" |
| "can I export", "allowed", "prohibited" | Policy Agent | "Can I export HS 070310?" |
| "rules of origin", "tariff benefits", "FTA", "ECTA", "CEPA", "customs procedures" | **Agreements Agent** | "Rules of origin for textiles to Australia" |
| "DGFT", "policy document" | Vector Agent | "DGFT policy for agricultural exports" |
| Data + policy/restrictions + agreements together | **Combined Agent** | "Show export values AND agreement benefits for chapter 07" |
| General questions | Synthesizer | "What is HS code?" |

## 🎨 Features

### ✅ Multi-Agent Orchestration
- Intelligent query routing (6 route types: SQL, Policy, Agreements, Vector, Combined, General)
- Combined agent for complex multi-faceted queries (SQL + Policy + Agreements)
- Result aggregation from multiple sources

### ✅ Source Attribution
- Every answer includes sources
- SQL queries shown
- Documents cited with relevance scores
- Timestamps for traceability

### ✅ Natural Language Processing
- Understands natural language queries
- Extracts entities (HS codes, countries)
- Context-aware responses

### ✅ Comprehensive Coverage
- Structured data (SQL)
- Unstructured documents (Vector)
- Business rules (Policy)
- Multi-source combined analysis (Combined)

### ✅ Error Handling
- Graceful degradation
- Informative error messages
- Fallback strategies

### ✅ Conversation Memory
- Per-session conversation history stored in memory
- All agents receive conversation context via `MessagesPlaceholder`
- SQL Agent uses history to resolve references ("show me data for it")
- Answer Synthesizer maintains conversational coherence
- Session management: create, clear, list, restore
- Frontend persists session ID via localStorage

## 🧠 Memory Architecture

### How Memory Works

```
┌─────────────────────────────────────────────────┐
│              ExportAdvisoryGraph                 │
│                                                  │
│  self.sessions = {                               │
│    "default": [HumanMsg, AIMsg, HumanMsg, ...], │
│    "session_123": [HumanMsg, AIMsg, ...],       │
│  }                                               │
└────────────────────┬────────────────────────────┘
                     │
            On each query:
            1. Add HumanMessage to session
            2. Pass full session history as state["messages"]
            3. All agents receive state["messages"]
            4. Add AIMessage to session after response
```

### Where Memory is Used

| Component | Uses History? | How |
|-----------|--------------|-----|
| **Query Router** | ✅ Yes | MessagesPlaceholder in routing prompt |
| **SQL Agent** | ✅ Yes | MessagesPlaceholder in SQL generation prompt |
| **Policy Agent** | ❌ No | Uses extracted HS code from router |
| **Agreements Agent** | ❌ No | Uses raw query text + extracted country |
| **Vector Agent** | ❌ No | Uses raw query text |
| **Combined Agent** | ✅ Yes | Runs SQL Agent (with history) + Policy batch check + Agreements |
| **Synthesizer** | ✅ Yes | MessagesPlaceholder in synthesis prompt |

### Multi-Turn Example

```python
graph = ExportAdvisoryGraph()

# Turn 1: Establish context
graph.query("What is HS 610910?", session_id="demo")
# Agent learns: HS 610910 = Cotton T-shirts

# Turn 2: Reference resolution
graph.query("Show me export data for it", session_id="demo")
# SQL Agent sees history → knows "it" = HS 610910
# Generates: SELECT * FROM export_statistics WHERE hs_code = '610910'

# Turn 3: Context carries forward  
graph.query("Can I export it to Australia?", session_id="demo")
# Policy Agent checks HS 610910 → Australia

# Turn 4: Implicit context
graph.query("What about UAE?", session_id="demo")
# Agent understands: same HS code, different country
```

### Session Management API

```python
# Create/use a session
result = graph.query("Hello", session_id="user_123")

# Get history
history = graph.get_session_history("user_123")
# Returns: [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "..."}]

# Get message count
count = graph.get_session_message_count("user_123")

# List all sessions
sessions = graph.list_sessions()

# Clear a session
graph.clear_session("user_123")
```

## 🔧 Configuration

Edit `config.py` for:
- Database connection
- Vector store paths
- Focus HS codes
- Target countries
- API keys

## 📈 Performance

- **Query Routing**: ~1-2 seconds
- **SQL Execution**: ~0.5-2 seconds
- **Vector Search**: ~1-3 seconds
- **Policy Check**: ~0.5-1 second
- **Total Response**: ~3-8 seconds (depends on query complexity)

## 🐛 Troubleshooting

### "No module named 'langgraph'"
```bash
pip install langgraph langchain-google-genai
```

### "Google API key required"
Add to `.env`:
```
GOOGLE_API_KEY=your_key_here
```

### "Database connection failed"
Check `.env` has correct database password

### "Vector stores not available"
Run agreements ingestion:
```bash
python storage-scripts/agreements_ingest_enhanced.py
```

## 🚀 Advanced Usage

### Custom Agent

```python
from agents.state import AgentState

class CustomAgent:
    def execute(self, state: AgentState) -> AgentState:
        # Your logic here
        state["custom_results"] = {...}
        state["next_agent"] = "synthesizer"
        return state

# Add to graph in agents/graph.py:
# workflow.add_node("custom", custom_agent.execute)
```

### Modify Routing Logic

Edit `agents/router.py` (the `QueryRouter.route()` method) or update the prompt in `prompts/router_prompt.py`.

### Modify SQL Generation

Edit `prompts/sql_schema.py` to update the database schema context, or edit `prompts/sql_prompt.py` to change how SQL is generated.

### Add New Data Sources

Extend `ExportDataIntegrator` in `export_data_integrator.py`

## 📚 API Reference

### ExportAdvisoryGraph

```python
class ExportAdvisoryGraph:
    def __init__(self, google_api_key: Optional[str] = None)
    def query(self, user_query: str, session_id: str = "default") -> Dict[str, Any]
    def format_response(self, result: Dict[str, Any]) -> str
    def clear_session(self, session_id: str = "default") -> None
    def get_session_history(self, session_id: str = "default") -> List[Dict[str, str]]
    def list_sessions(self) -> List[str]
    def get_session_message_count(self, session_id: str = "default") -> int
```

### `AgentState` (defined in `agents/state.py`)

```python
class AgentState(TypedDict):
    messages: Sequence[BaseMessage]  # Full conversation history for context
    user_query: str
    query_type: str                  # 'sql', 'vector', 'policy', 'agreements', 'general', 'combined'
    hs_code: Optional[str]
    country: Optional[str]
    sql_results: Optional[Dict]
    vector_results: Optional[List[Dict]]
    policy_results: Optional[Dict]
    agreement_results: Optional[List[Dict]]  # Trade agreement search results
    final_answer: Optional[str]
    sources: List[Dict[str, Any]]
    next_agent: Optional[str]
```

## 🎯 Next Steps

1. **Test the system**: `python test_agreement_queries.py --quick`
2. **Try interactive mode**: `python -m agents.graph`
3. **Run the web app**: `python app.py` → http://localhost:8000
4. **Test memory**: Use multi-turn conversations in the web UI
5. **Customize agents** — edit files in `agents/` and `prompts/`
6. **Add more data sources** by extending `export_data_integrator.py`

---

**Built with LangGraph, LangChain, Google Gemini, FAISS, ChromaDB, and FastAPI** 🚀  
**Last Updated**: February 23, 2026  
**Version**: 4.0 (Modular refactoring)
