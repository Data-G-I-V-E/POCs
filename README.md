# Export Advisory Multi-Agent System

A sophisticated LangGraph-based multi-agent system for export policy analysis, trade data queries, and compliance checking for Indian exports — with a full-featured FastAPI backend and premium dark-theme web UI.

## 🎯 Overview

This system provides intelligent export advisory services by integrating:
- **PostgreSQL Database**: Trade statistics (annual + monthly), HS codes, export policies, restrictions
- **Trade Agreements RAG Store**: 2,524 article-aware chunks from 141 FTA PDFs (FAISS + ChromaDB with cross-reference resolution)
- **DGFT FTP RAG Store**: 413 section-aware chunks from 11 Foreign Trade Policy chapter PDFs (FAISS + ChromaDB)
- **LLM Integration**: Anthropic Claude Sonnet 4 for intelligent query routing and synthesis
- **HS Master Table**: 13,407 eight-digit HS codes extracted from master PDF, searchable via full-text + fuzzy matching
- **Multi-Agent Architecture**: 7 specialized agents — SQL, Policy, Agreements, Vector, HS Lookup, Combined, and Answer Synthesizer
- **Smart Routing**: LLM-powered product extraction + auto-upgrade to Combined mode so ALL data sources are checked
- **Conversation Memory**: Per-session conversation history with context-aware multi-turn support
- **FastAPI Backend**: RESTful API with session management, trade data visualization, and restriction checks
- **Web UI**: Premium dark-theme interface with charts, markdown rendering, and real-time interaction

## 🏗️ System Architecture

```
                          ┌────────────────────┐
                          │    Web UI (HTML/JS) │
                          │  • Chat Interface   │
                          │  • Chart.js Viz     │
                          │  • Session Memory   │
                          └─────────┬──────────┘
                                    │ HTTP/REST
                          ┌─────────▼──────────┐
                          │   FastAPI Backend   │
                          │  • /api/chat        │
                          │  • /api/trade-data  │
                          │  • /api/session/*   │
                          │  • /api/export-check│
                          └─────────┬──────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │     ExportAdvisoryGraph        │
                    │   (LangGraph Orchestrator)     │
                    │   • Session-based memory       │
                    │   • Conversation history       │
                    └───────────────┬───────────────┘
                                    │
             ┌──────────────────────▼──────────────────────┐
             │              QUERY ROUTER                    │
             │  • LLM-based classification + product name   │
             │  • HS code regex + 13K master table lookup   │
             │  • Full-text search on hs_master_8_digit     │
             │  • Auto-upgrade: HS+country → combined       │
             └──┬──────┬──────┬──────┬──────┬──────┬───────┘
                │      │      │      │      │      │
           (Router picks ONE path based on query type)
                │      │      │      │      │      │
         ┌──────▼──┐┌──▼───┐┌─▼────┐┌▼─────┐┌▼──────────┐ ┌────▼─────┐
         │SQL Agent││Policy││Agree-││Vector││HS Lookup  │ │ general  │
         │         ││Agent ││ments ││Agent ││Agent      │ │(no agent)│
         │Text→SQL ││      ││Agent ││      ││           │ └────┬─────┘
         │+History ││Check:││      ││DGFT+ ││Search     │      │
         │         ││Proh. ││FTA   ││Agree ││13K codes  │      │
         │Postgres ││Rest. ││PDFs  ││PDFs  ││exact/FTS/ │      │
         │stats,   ││STE   ││Cross-││      ││fuzzy      │      │
         │monthly  ││ITC   ││refs  ││      ││           │      │
         │views    ││Notes ││      ││      ││           │      │
         └───┬─────┘└──┬───┘└──┬───┘└──┬───┘└─────┬─────┘     │
             │         │       │       │          │            │
             │         │       │       │ ┌────────────────┐    │
             │         │       │       │ │ COMBINED Agent │    │
             │         │       │       │ │ (sequential)   │    │
             │         │       │       │ │                │    │
             │         │       │       │ │ 1. SQL Agent   │    │
             │         │       │       │ │ 2. Policy Agent│    │
             │         │       │       │ │ 3. Agreements  │    │
             │         │       │       │ │    (if country)│    │
             │         │       │       │ │ 4. DGFT FTP    │    │
             │         │       │       │ │    retriever   │    │
             │         │       │       │ └───────┬────────┘    │
             │         │       │       │         │             │
             └─────────┴───────┴───────┴─────────┴─────────────┘
                                │
              ┌─────────────────▼──────────────────┐
              │        Answer Synthesizer           │
              │  • Combines all agent results       │
              │  • Markdown output + source cites   │
              │  • Chapter notes integration        │
              │  • Context-aware (uses history)     │
              └─────────────────┬──────────────────┘
                                │
              ┌─────────────────▼──────────────────┐
              │          Final Response              │
              │    + Sources + Meta + Timestamps     │
              └────────────────────────────────────┘
```

## 📁 Project Structure

```
POCs/
├── app.py                         # FastAPI backend with all API endpoints
├── config.py                      # Centralized configuration (DB, LLM, paths)
├── langgraph_export_agent.py      # Backward-compat shim → re-exports from agents/
├── export_data_integrator.py      # Unified data access layer
├── requirements.txt               # Python dependencies
│
├── agents/                        # Multi-agent system (modular package)
│   ├── __init__.py               # Re-exports all public symbols
│   ├── state.py                  # AgentState TypedDict (shared across agents)
│   ├── router.py                 # QueryRouter — LLM query classification
│   ├── sql_agent.py              # SQLAgent — text-to-SQL with conversation context
│   ├── policy_agent.py           # PolicyAgent — export restriction checks
│   ├── vector_agent.py           # VectorAgent — DGFT FTP + agreements vector search
│   ├── agreements_agent.py       # AgreementsAgent — trade agreement search + cross-refs + article lookup
│   ├── hs_lookup_agent.py        # HSLookupAgent — 13K HS code search (exact/prefix/FTS/fuzzy)
│   ├── synthesizer.py            # AnswerSynthesizer — combines agent results
│   └── graph.py                  # ExportAdvisoryGraph orchestrator + demo
│
├── prompts/                       # LLM prompts (separated for easy editing)
│   ├── __init__.py
│   ├── router_prompt.py          # Query routing classification prompt
│   ├── sql_schema.py             # Database schema context (tables, views, functions)
│   ├── sql_prompt.py             # SQL generation system prompt
│   └── synthesizer_prompt.py     # Answer synthesis system prompt
│
├── static/                        # Web UI frontend
│   ├── index.html                # Main page (dark theme)
│   ├── styles.css                # Premium CSS design system
│   └── app.js                    # Frontend logic with chart.js & markdown
│
├── storage-scripts/               # Data ingestion & setup
│   ├── database_unification.py   # Creates unified SQL views
│   ├── run_schema.py             # Runs all SQL schema files
│   ├── itc_data_loader.py        # ITC HS code data loader
│   ├── itc_bulk.py               # Bulk loader for itc_hs_products
│   ├── restrictions.py           # Prohibited/restricted items
│   ├── ste_items.py              # STE requirements
│   ├── agreements_ingest_enhanced.py  # Trade agreement PDF ingestion
│   ├── agreements_retriever.py   # Agreement search with cross-ref resolution
│   ├── dgft_ftp_ingest.py        # DGFT FTP chapter PDF ingestion
│   ├── dgft_ftp_retriever.py     # DGFT FTP search with section lookup
│   ├── monthly_trade_loader.py   # Monthly 2024 trade data (xlsx → PostgreSQL)
│   ├── export_data.py            # Export data utilities
│   ├── export_data_schema.sql    # Export statistics schema
│   ├── hs_codes.sql              # HS codes table schema
│   ├── itc_hs_schema.sql         # ITC HS products schema
│   ├── prohibited_restricted.sql # Prohibited/restricted items schema
│   ├── ste-schema.sql            # STE items schema
│   └── hs_master_loader.py       # Extracts 13K HS codes from master PDF → PostgreSQL
│
├── data/                          # Source data
│   ├── master_hs_codes.pdf        # Master HS code PDF (461 pages, 13,407 codes)
│   ├── agreements/                # Trade agreement PDFs (AUS, UAE, UK)
│   │   ├── australia/            # 34 PDFs (AI-ECTA chapters, annexes, schedules)
│   │   ├── uae/                  # 39 PDFs (India-UAE CEPA)
│   │   └── uk/                   # 68 PDFs (India-UK CETA)
│   ├── policies/
│   │   └── DGFT_FTP/             # DGFT Foreign Trade Policy (11 chapter PDFs)
│   │       ├── Ch-1.pdf ... Ch-11.pdf
│   └── trade_data/                # Export statistics (annual + monthly)
│       └── dgft_tradestat/2024/   # 567 xlsx files (16 HS × 3 countries × 12 months)
│
├── agreements_rag_store/          # Trade agreements vector store (generated)
│   ├── agreements.index           # FAISS index (2,524 vectors, cosine similarity)
│   ├── agreements_chroma/         # ChromaDB with metadata filtering
│   ├── documents.json             # Chunk text + metadata (2,524 chunks)
│   ├── article_index.json         # Article cross-reference index (885 articles)
│   ├── chunk_id_mapping.json      # Chunk ID → FAISS position mapping
│   └── ingestion_stats.json       # Ingestion statistics
│
├── dgft_ftp_rag_store/            # DGFT FTP policy vector store
│   ├── dgft_ftp.index             # FAISS index (413 vectors)
│   ├── dgft_ftp_chroma/           # ChromaDB with chapter/section filtering
│   ├── documents.json             # Chunk text + metadata (413 chunks)
│   └── section_index.json         # Section → chunk position mapping (264 sections)
│
├── dgft_output/                   # DGFT FTP parsed article/table data (generated)
│   ├── master_index.json          # Article index: chapter → articles → cross-refs, tables
│   ├── table_metadata.json        # Table metadata: table_id, parent_article, chapter
│   └── tables_raw.json            # Full extracted table content (HTML + text)
│
├── test_agreement_queries.py      # 19 test queries (agreements, SQL, policy, monthly)
├── DATA_STORAGE.md                # Data architecture documentation
├── LANGGRAPH_GUIDE.md             # LangGraph system documentation
└── README.md                      # This file
```

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL database
- Anthropic API key

### 1. Install Dependencies
```bash
conda activate rag_env
pip install -r requirements.txt
```

### 2. Configure Environment
Create `.env` file:
```env
# Database (these are what config.py reads)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=PPL-AI
DB_USER=postgres
DB_PASSWORD=your_password

# Anthropic API
ANTHROPIC_API_KEY=your_api_key_here
```

### 3. Setup Database
```bash
# Run schema setup
python storage-scripts/run_schema.py

# Load HS codes and policies
python storage-scripts/itc_data_loader.py
python storage-scripts/restrictions.py
python storage-scripts/ste_items.py

# Create unified views
python storage-scripts/database_unification.py
```

### 4. Ingest Trade Agreements
```bash
# Ingest 141 trade agreement PDFs into FAISS + ChromaDB
python storage-scripts/agreements_ingest_enhanced.py
```

This processes 108 documents (skips 21 tariff schedule PDFs), creating:
- **2,524 chunks** with article-level metadata
- **888 articles** parsed across 3 countries
- **885 articles** indexed for cross-reference resolution
- **1,201 chunks** (~48%) with cross-references

### 5. Ingest DGFT Foreign Trade Policy
```bash
# Ingest 11 DGFT FTP chapter PDFs into FAISS + ChromaDB
python storage-scripts/dgft_ftp_ingest.py
```

This processes 11 chapters, creating:
- **413 chunks** with section-level metadata
- **264 sections** indexed for direct lookup (e.g., Section 7.02)
- Section-aware chunking (splits on DGFT numbering like 7.01, 7.02)

### 6. Load Monthly Trade Data
```bash
# Load 567 monthly xlsx files into PostgreSQL
python storage-scripts/monthly_trade_loader.py
```
Creates `monthly_export_statistics` table with 565 records, plus `v_monthly_exports` and `v_quarterly_exports` views.

### 7. Run the Application
```bash
python app.py
```

Open your browser to:
- **Frontend**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

### 8. Test Programmatically
```python
from agents import ExportAdvisoryGraph  # or: from langgraph_export_agent import ...

# Initialize agent
graph = ExportAdvisoryGraph()

# Ask a question (with session memory)
result = graph.query("Can I export HS 070310 to Australia?", session_id="demo")
print(graph.format_response(result))

# Follow-up (agent remembers context)
result2 = graph.query("What about UAE?", session_id="demo")
print(graph.format_response(result2))
```

## 🎨 Features

### ✅ Multi-Agent Routing (7 Agents + Smart Upgrade)
- **Query Router**: LLM-powered classification with **LLM-based product name extraction** (no brittle regex — LLM understands "cows" from "i want to export cows to uae") + full-text search across **13,407 HS codes** in `hs_master_8_digit` table
- **SQL Agent**: Text-to-SQL with full conversation history for context-aware queries
- **Policy Agent**: Checks prohibited/restricted/STE items with prefix matching (6→8 digit) + **ITC chapter notes** (main notes, export licensing, policy conditions)
- **Agreements Agent**: Searches trade agreement PDFs with article-level precision, auto cross-reference resolution, and direct article lookup (e.g., "Article 4.5")
- **Vector Agent**: Searches BOTH DGFT FTP policy chapters (413 chunks) AND trade agreements (2,524 chunks)
- **HS Lookup Agent**: Searches the 13,407-code master HS table via exact match, prefix, full-text search, and fuzzy keyword fallback. Returns multiple matches when ambiguous so the user can pick the right code
- **Combined Agent**: Runs SQL → Policy → Agreements (if country) → DGFT FTP **sequentially** for comprehensive answers. Auto-triggered when HS code + country detected.
- **Answer Synthesizer**: Combines results with source attribution, article/section citations, HS code disambiguation tables, chapter notes, and markdown formatting
- **Auto-Upgrade**: Product queries with HS codes auto-upgrade to Combined mode, ensuring trade stats + policy + agreements + DGFT FTP are all checked

### ✅ Trade Agreements RAG (NEW)
- **141 PDFs** ingested from 3 FTAs: India-Australia ECTA, India-UAE CEPA, India-UK CETA
- **Article-aware chunking**: Splits on `Article X.Y` boundaries (not blind fixed-size windows)
- **Cross-reference resolution**: When Article 4.3 mentions Article 4.6, both are returned
- **OCR cleanup**: Fixes 15+ common OCR errors from scanned UAE PDFs
- **Smart file skipping**: Skips massive tariff schedule tables (already in PostgreSQL)
- **Dual storage**: FAISS (vector search) + ChromaDB (metadata filtering by country/doc_type)
- **885 articles** indexed with cross-reference mapping

### ✅ Conversation Memory
- **Per-session history**: Each session maintains full conversation history
- **Context-aware agents**: SQL Agent and Synthesizer use conversation history to resolve references
- **Multi-turn support**: "Show me data for it" works after discussing a specific HS code
- **Session persistence**: Frontend stores session ID in localStorage
- **History restoration**: Previous messages restored on page refresh

### ✅ Policy Reference Resolution
- Tracks 57 HS codes with conditional export requirements
- Links policies like "Policy Condition 1" to full text definitions
- Prefix matching: 6-digit queries match 8-digit entries in restricted/prohibited tables
- Supports chapter-level and item-level policy conditions

### ✅ Premium Web UI
- Dark theme with glassmorphism effects
- Markdown rendering for rich agent responses
- Chart.js visualizations for trade data
- Animated loading states and micro-interactions
- Responsive design for mobile and desktop
- Session management (new/clear/restore)

### ✅ Comprehensive Data Coverage
- **16 Focus HS Codes** across 6 chapters (07, 08, 61, 62, 85, 90)
- **3 Target Countries**: Australia, UAE, UK
- **Export Statistics**: Annual trade data by HS code, country, year
- **Monthly Statistics**: 2024 month-by-month exports (565 records across 12 months)
- **Views**: `v_monthly_exports` (with names), `v_quarterly_exports` (aggregated by quarter)
- **Policy Tracking**: Prohibited, restricted, STE classifications
- **Trade Agreements**: 2,524 article-aware chunks across 3 FTAs
- **DGFT FTP Policies**: 413 section-aware chunks across 11 chapters (Ch-1 to Ch-11)

### ✅ Source Attribution
Every answer includes:
- SQL queries executed
- Database tables accessed
- Trade agreement article references (e.g., "Article 4.3 of AI-ECTA")
- Vector search results with relevance scores
- Cross-reference resolution indicators
- Timestamps for traceability

## 🔌 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serve web UI |
| `GET` | `/api/health` | Health check |
| `POST` | `/api/chat` | Chat with multi-agent system |
| `GET` | `/api/session/{id}/history` | Get session conversation history |
| `DELETE` | `/api/session/{id}` | Clear session history |
| `GET` | `/api/sessions` | List all active sessions |
| `POST` | `/api/trade-data` | Get trade data for visualization |
| `GET` | `/api/hs-code/{hs_code}` | Get HS code information |
| `POST` | `/api/monthly-trade-data` | Get monthly trade data for line charts |
| `GET` | `/api/export-check` | Check export eligibility (HS + country) |
| `GET` | `/api/restriction-check` | Check restriction status (prefix-aware) |
| `GET` | `/api/focus-codes` | Get list of focus HS codes |

## 📊 Database Schema

### Key Tables
```sql
-- Unified policy view (includes policy references)
v_export_policy_unified
  - hs_code, hs_description, chapter_number
  - itc_policy, policy_reference, policy_reference_text
  - is_prohibited, is_restricted, is_ste
  - overall_status (FREE/PROHIBITED/RESTRICTED/STE_ONLY/CONDITIONAL)

-- Annual export statistics
export_statistics
  - hs_code, country_code, year_label, export_value_crore

-- Monthly export statistics (2024)
monthly_export_statistics
  - hs_code, country_code, year, month, month_name
  - export_value_crore, prev_year_value_crore, monthly_growth_pct
  - ytd_value_crore, ytd_growth_pct

-- Monthly exports enriched with names (VIEW)
v_monthly_exports
  - All columns from monthly_export_statistics + hs_description, country_name, chapter

-- Quarterly aggregations (VIEW)
v_quarterly_exports
  - hs_code, country_code, quarter, quarterly_export_crore, quarterly_growth_pct

-- Policy references
itc_hs_policy_references    -- HS code → policy mapping (57 rows)
itc_chapter_policies        -- Policy definitions (385 rows)
itc_chapter_notes           -- Chapter notes (446 rows)
```

### Functions
```sql
-- Check export feasibility
SELECT * FROM get_export_feasibility('070310', 'AUS');

-- Search HS codes
SELECT * FROM search_hs_codes('onion');

-- Get chapter policies
SELECT * FROM get_chapter_export_policies('07');
```

## 🤖 Example Queries

### Query Types

**1. SQL Queries** (Data aggregation)
```
"What is the total export value for chapter 07?"
"Show export statistics for HS 610910 to UAE"
"What are all the prohibited items?"
"List all restricted items"
"What were the monthly exports of HS 610910 to UAE in 2024?"
"Which month had the highest exports for chapter 85 to Australia?"
"Show quarterly export trend for textiles to UK in 2024"
```

**2. Policy Checks** (Export feasibility)
```
"Can I export HS 070310 to Australia?"
"Are there any restrictions on electronic cigarettes?"
"Is HS 850440 prohibited or restricted?"
```

**3. Multi-turn Conversations** (Memory)
```
Turn 1: "What is HS 610910?"
Turn 2: "Show me export data for it"       ← resolves "it" from history
Turn 3: "Can I export it to Australia?"     ← still remembers HS 610910
Turn 4: "What about UAE?"                   ← remembers context
```

**4. Trade Agreements** (Agreement search with cross-reference resolution)
```
"What are the rules of origin for exporting textiles to Australia?"
"What tariff benefits does the India-UAE CEPA provide for agricultural products?"
"What are the customs procedures under the India-UK FTA?"
"What does Article 4.3 of the India-Australia agreement say about goods not wholly produced?"
"Explain the certificate of origin requirements for UK exports"
"What SPS measures are in the India-UAE CEPA?"
```

**5. HS Lookup Queries** (Finding 8-digit HS codes by product description)
```
"What is the HS code for mangoes?"
"What HS codes cover edible fruit and nuts?"
"Find HS classification for electronic cigarettes"
"Which chapter does basmati rice fall under?"
"Show all 8-digit codes for cotton T-shirts"
```

**6. Combined Queries** (Multi-agent — SQL + Policy + Agreements together)
```
"Can I export vegetables to Australia and what does the trade agreement say about tariff benefits?"
"Show me export data AND restrictions AND agreement provisions for chapter 07"
"What are the export values and trade agreement benefits for textiles to UAE?"
"Compare chapters 61 and 07 with their policy conditions and STE requirements"
```

## 🔧 Configuration

### Focus HS Codes (Chapter-wise)
```python
FOCUS_HS_CODES = [
    # Chapter 07 - Vegetables
    '070310', '070700', '070960',
    # Chapter 08 - Fruits
    '080310', '080410', '080450',
    # Chapter 61 - Knitted apparel
    '610910', '610342', '610442',
    # Chapter 62 - Woven apparel
    '620342', '620462', '620520',
    # Chapter 85 - Electrical equipment
    '850440', '851310', '851762',
    # Chapter 90 - Optical instruments
    '902610'
]
```

### Target Countries
```python
TARGET_COUNTRIES = ['australia', 'uae', 'uk']
COUNTRY_CODES = {
    'australia': 'AUS',
    'uae': 'UAE',
    'uk': 'GBR'
}
```

## 🎯 Data Statistics

### Current Coverage
- **HS Master Codes**: 13,407 eight-digit codes across 97 chapters in `hs_master_8_digit` (+ 31 focus codes in `hs_codes`, 2,006 in `itc_hs_products`)
- **HS Codes with Policy References**: 57
- **Export Statistics**: Multi-year data for 3 countries
- **Prohibited Items**: Complete list
- **Restricted Items**: Complete list
- **STE Items**: Complete list
- **Policy Definitions**: 385 chapter-level policies
- **Chapter Notes**: 446 guidance notes

### Trade Agreements Coverage
| Country | Agreement | PDFs | Processed | Chunks | Articles | Cross-refs |
|---------|-----------|------|-----------|--------|----------|------------|
| Australia | AI-ECTA | 34 | 24 | 577 | 190 | 231 |
| UAE | India-UAE CEPA | 39 | 35 | 751 | 249 | 209 |
| UK | India-UK CETA | 68 | 49 | 1,196 | 449 | 761 |
| **Total** | | **141** | **108** | **2,524** | **888** | **1,201** |

- 21 PDFs skipped (large tariff schedule tables — data already in PostgreSQL)
- 885 unique articles indexed for cross-reference resolution

## 🔮 Future Enhancements

### Planned Features
- [ ] OCR for scanned-only PDFs (8 UK correspondence letters)
- [ ] Extract tariff schedules from agreements
- [ ] Add more countries (ASEAN, EU, US)
- [ ] Real-time policy update tracking
- [ ] Multi-language support
- [ ] Automated policy change alerts
- [ ] Persistent session storage (database-backed)

## 📞 System Status

### ✅ Operational Components
- **Modular agent package** (`agents/`) — one class per agent, clean separation of concerns
- **Prompt management** (`prompts/`) — all LLM prompts in editable Python files
- **Backward-compat shim** (`langgraph_export_agent.py`) — re-exports from `agents/`
- PostgreSQL database with unified views
- Policy references system (57 codes)
- Export data integrator with prefix matching
- LangGraph multi-agent system with conversation memory (7 agents)
- SQL Agent (text-to-SQL with schema context + history) — `agents/sql_agent.py`
- Policy Agent (export feasibility checks with prefix matching) — `agents/policy_agent.py`
- Agreements Agent (trade agreement search + cross-ref resolution) — `agents/agreements_agent.py`
- Vector Agent (DGFT policies) — `agents/vector_agent.py`
- HS Lookup Agent (13,407-code master HS table, exact/FTS/fuzzy) — `agents/hs_lookup_agent.py`
- Combined Agent (SQL + Policy + Agreements for complex queries) — `agents/graph.py`
- Answer Synthesizer (markdown output + source attribution) — `agents/synthesizer.py`
- FastAPI backend with full REST API
- Premium dark-theme web UI with Chart.js visualizations
- Trade agreements RAG store (2,524 chunks, 885 articles, FAISS + ChromaDB)

## 🐛 Troubleshooting

### Database Connection Issues
```bash
# Check .env file has correct credentials
# Test connection
python -c "from config import Config; import psycopg2; psycopg2.connect(**Config.DB_CONFIG)"
```

### Import Errors
```bash
# Ensure all dependencies installed
pip install -r requirements.txt

# Key dependencies
pip install langgraph langchain-anthropic psycopg2 chromadb
```

### Missing Tables
```bash
# Re-run database unification
python storage-scripts/database_unification.py
```

### Server Won't Start
```bash
# Check if port 8000 is already in use
# On Windows:
netstat -ano | findstr :8000
```

## 📚 Documentation

- **[DATA_STORAGE.md](DATA_STORAGE.md)**: Complete data architecture documentation (includes agreements storage)
- **[LANGGRAPH_GUIDE.md](LANGGRAPH_GUIDE.md)**: Detailed LangGraph system architecture, modular agents, prompt management
- **[test_agreement_queries.py](test_agreement_queries.py)**: 19 test queries (agreements, SQL, policy, monthly data)

## 📄 License

Internal project for PPL+AI internship.

## 👥 Contributors

Developed as part of PPL+AI internship assignment.

---

**Last Updated**: March 8, 2026
**System Version**: 6.1 (HS Lookup Agent wired as graph node + HS_LOOKUP routing)
**Status**: ✅ Fully Operational (modular agents/ package, 7 agents wired in graph, 13K HS master codes, Agreements RAG + DGFT FTP RAG live, Smart Combined routing, HS_LOOKUP route, LLM product extraction, FastAPI + Web UI, Memory enabled)
