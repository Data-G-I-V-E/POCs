"""
LangGraph Multi-Agent Export Advisory System

A sophisticated multi-agent system using LangGraph that:
1. Routes queries to appropriate specialized agents
2. Executes SQL queries when needed (text-to-SQL)
3. Searches vector stores for policies and agreements
4. Searches trade agreements with cross-reference resolution
5. Provides sources and citations for all answers
6. Combines results from multiple agents

Agents:
- SQL Agent: Executes database queries for structured data
- Vector Agent: Searches DGFT policies (legacy)
- Agreements Agent: Searches trade agreements (FAISS/ChromaDB with cross-refs)
- Export Policy Agent: Checks restrictions and requirements
- Orchestrator: Routes and combines results
"""

import os
from typing import TypedDict, Annotated, Sequence, List, Dict, Any, Optional
from datetime import datetime
import operator

# LangGraph and LangChain imports
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser

# Local imports
from config import Config
from export_data_integrator import ExportDataIntegrator

import psycopg2
import re


# ========== STATE DEFINITION ==========

class AgentState(TypedDict):
    """State passed between agents"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_query: str
    query_type: str  # 'sql', 'vector', 'policy', 'general', 'agreements', 'combined'
    hs_code: Optional[str]
    country: Optional[str]
    sql_results: Optional[Dict]
    vector_results: Optional[List[Dict]]
    policy_results: Optional[Dict]
    agreement_results: Optional[List[Dict]]  # Trade agreement search results
    final_answer: Optional[str]
    sources: List[Dict[str, Any]]
    next_agent: Optional[str]


# ========== AGENTS ==========

class QueryRouter:
    """Routes queries to appropriate agents"""
    
    def __init__(self, llm):
        self.llm = llm
        self.routing_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a query router for an export advisory system.
            
Analyze the user query and determine what type of agents are needed:

1. SQL Agent - For queries about:
   - Export statistics, trade data, numbers
   - Historical export values
   - Monthly export data, trends, seasonal patterns
   - "What were monthly exports of X to Y?"
   - "Show month-by-month trend", "best month", "quarterly exports"
   - Chapter summaries, aggregations
   - "How many", "What is the total", "Show me all"
   - "What are prohibited items", "List restricted items", "Show STE items"
   - ANY query asking for a LIST or TABLE of items (prohibited, restricted, STE, etc.)
   
2. Policy Agent - For queries about:
   - "Can I export X?" (specific HS code)
   - Checking if a SPECIFIC item is allowed/prohibited/restricted
   - Compliance checks for a SPECIFIC HS code
   - NOT for listing all prohibited/restricted items
   
3. AGREEMENTS Agent - For queries about:
   - Trade agreements between India and partner countries (Australia/AI-ECTA, UAE/CEPA, UK/CETA)
   - Rules of origin for a specific country
   - Tariff commitments or concessions under FTAs
   - Customs procedures and trade facilitation under agreements
   - Certificate of origin requirements
   - SPS (sanitary/phytosanitary) measures in agreements
   - TBT (technical barriers to trade)
   - Dispute settlement procedures
   - Services trade commitments
   - "What does the India-Australia agreement say about..."
   - "Rules of origin for textile exports to UAE"
   - "Tariff benefits under UK FTA"
   
4. Vector Agent - For queries about:
   - DGFT policies, FTP chapters
   - General policy documents
   
5. General Agent - For:
   - Simple definitions
   - Explanations
   - General questions

6. COMBINED - For COMPLEX queries that need BOTH data AND policy/agreement checks:
   - Export data + restrictions for a chapter/product
   - "Which HS codes are restricted AND what are their export values?"
   - "Can I export chapter 07 items and what are the values?"
   - "What are the tariff benefits AND export values for textiles to Australia?"
   - Queries asking about BOTH statistics/values AND policy/restrictions/STE
   - Queries mentioning multiple chapters or products needing both data + compliance
   - Queries needing BOTH database data AND agreement/policy information
   - Comparison queries that need export values + policy status together

IMPORTANT: 
- "What are prohibited items?" → SQL (listing data only)
- "Can I export HS 070310?" → POLICY (specific check only)
- "Rules of origin for Australia" → AGREEMENTS (agreement lookup)
- "What tariff benefits does the UAE CEPA provide?" → AGREEMENTS
- "Show export values AND restrictions for chapter 07" → COMBINED (needs both)
- "Compare chapters 61 and 07 with their policy conditions" → COMBINED (needs both)
- "Can I export vegetables to Australia and what does the trade agreement say?" → COMBINED
- "Monthly exports of textiles to UAE" → SQL (monthly data query)
- "Which month had the highest exports?" → SQL (monthly data query)
- "Quarterly trend for chapter 85 exports" → SQL (monthly data query)

Respond with ONE of: SQL, POLICY, AGREEMENTS, VECTOR, GENERAL, COMBINED

Also extract if present:
- HS Code (6-digit code)
- Country (australia, uae, uk)"""),
            MessagesPlaceholder(variable_name="messages"),
            ("human", "Query: {query}")
        ])
    
    def _find_hs_code_by_description(self, query: str) -> Optional[str]:
        """Find HS code by searching product descriptions in database"""
        try:
            conn = psycopg2.connect(**Config.DB_CONFIG)
            cursor = conn.cursor()
            
            # Search in prohibited items
            cursor.execute("""
                SELECT hs_code, description 
                FROM prohibited_items 
                WHERE description ILIKE %s
                LIMIT 1
            """, (f'%{query}%',))
            result = cursor.fetchone()
            
            if result:
                cursor.close()
                conn.close()
                return result[0]
            
            # Search in restricted items
            cursor.execute("""
                SELECT hs_code, description 
                FROM restricted_items 
                WHERE description ILIKE %s
                LIMIT 1
            """, (f'%{query}%',))
            result = cursor.fetchone()
            
            if result:
                cursor.close()
                conn.close()
                return result[0]
            
            # Search in hs_codes table
            cursor.execute("""
                SELECT hs_code, description 
                FROM hs_codes 
                WHERE description ILIKE %s
                LIMIT 1
            """, (f'%{query}%',))
            result = cursor.fetchone()
            
            if result:
                cursor.close()
                conn.close()
                return result[0]
            
            # Search in itc_hs_products table
            cursor.execute("""
                SELECT hs_code, description 
                FROM itc_hs_products 
                WHERE description ILIKE %s
                LIMIT 1
            """, (f'%{query}%',))
            result = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            return result[0] if result else None
            
        except Exception as e:
            print(f"Error searching for HS code: {e}")
            return None
    
    def route(self, state: AgentState) -> AgentState:
        """Route the query to appropriate agent"""
        response = self.routing_prompt | self.llm | StrOutputParser()
        result = response.invoke({
            "messages": state["messages"],
            "query": state["user_query"]
        })
        
        # Extract query type
        result_upper = result.upper()
        if "COMBINED" in result_upper:
            query_type = "combined"
        elif "SQL" in result_upper:
            query_type = "sql"
        elif "POLICY" in result_upper:
            query_type = "policy"
        elif "AGREEMENT" in result_upper:
            query_type = "agreements"
        elif "VECTOR" in result_upper:
            query_type = "vector"
        else:
            query_type = "general"
        
        # Extract HS code and country
        query_lower = state["user_query"].lower()
        hs_match = re.search(r'\b(\d{6,8})\b', state["user_query"])
        hs_code = hs_match.group(1) if hs_match else None
        
        # If no HS code found and query is about policies/restrictions,
        # try to find HS code from product description
        if not hs_code and query_type == "policy":
            # Extract potential product name from query
            # Remove common question words and phrases (order matters - longer phrases first)
            product_query = query_lower
            
            # List of phrases to remove (longer/more specific first)
            remove_phrases = [
                "are there any restrictions on",
                "are there any restriction on", 
                "is there any restriction on",
                "are there restrictions on",
                "is there restriction on",
                "any restrictions on",
                "any restriction on",
                "can i export",
                "export of",
                "exporting",
                "restrictions for",
                "restriction for",
                "prohibited",
                "allowed",
                "allowed to export",
                "permitted to export",
                "?",
            ]
            
            for phrase in remove_phrases:
                product_query = product_query.replace(phrase, "")
            
            product_query = product_query.strip()
            
            if len(product_query) > 3:  # Only search if we have meaningful text
                hs_code = self._find_hs_code_by_description(product_query)
        
        country = None
        for c in Config.TARGET_COUNTRIES:
            if c in query_lower:
                country = c
                break
        
        state["query_type"] = query_type
        state["hs_code"] = hs_code
        state["country"] = country
        state["next_agent"] = query_type
        
        return state


class SQLAgent:
    """Text-to-SQL agent for database queries"""
    
    def __init__(self, llm):
        self.llm = llm
        self.db_config = Config.DB_CONFIG
        
        # Database schema context
        self.schema_context = """
Available Tables and Views:

1. v_export_policy_unified - Unified export policies
   Columns: hs_code, hs_description, chapter_number, itc_policy, policy_reference, policy_reference_text,
            is_prohibited, is_restricted, is_ste, prohibited_condition, restricted_condition, overall_status
   Note: policy_reference contains references like "Policy Condition 1", policy_reference_text has full policy text

2. prohibited_items - Items prohibited from export
   Columns: id, hs_code, description, export_policy, policy_condition
   Use this to list ALL prohibited items or search for specific prohibited items

3. restricted_items - Items with export restrictions
   Columns: id, hs_code, description, export_policy, policy_condition
   Use this to list ALL restricted items or search for specific restricted items

4. ste_items - State Trading Enterprise items
   Columns: id, hs_code, description, export_policy, authorized_entity, policy_condition
   Use this to list ALL STE items or find which entity can export specific items

5. itc_hs_policy_references - Policy references for HS codes
   Columns: hs_code, policy_reference, chapter_code, notification_no, notification_date
   Use this to find HS codes that refer to chapter policies

6. itc_chapter_policies - Chapter-wise policy definitions
   Columns: chapter_code, policy_type, policy_text, notification_no, notification_date
   Contains actual policy text for references like "Policy Condition 1"

7. itc_chapter_notes - Chapter notes and additional information
   Columns: chapter_code, note_type, sl_no, note_text, notification_no
   Types: 'main_note', 'policy_condition', 'export_licensing'

8. export_statistics - Annual export trade data
   Columns: hs_code, country_code, year_label, export_value_crore

9. monthly_export_statistics - Monthly export data for 2024
   Columns: hs_code, country_code, year, month (1-12), month_name (Jan-Dec),
            export_value_crore, prev_year_value_crore, monthly_growth_pct,
            ytd_value_crore, prev_ytd_value_crore, ytd_growth_pct,
            total_monthly_value_crore, total_ytd_value_crore
   USE THIS TABLE for any question about monthly, seasonal, or trend data in 2024
   Data: 16 HS codes × 3 countries × 12 months = 565 records

10. v_monthly_exports - Monthly exports with country names and HS descriptions (VIEW)
    Columns: hs_code, chapter (VARCHAR - use quotes e.g. chapter = '85'), hs_description, country_code, country_name,
             year, month (INTEGER 1-12), month_name (VARCHAR 'Jan'-'Dec'), export_value_crore, prev_year_value_crore,
             monthly_growth_pct, ytd_value_crore, prev_ytd_value_crore, ytd_growth_pct,
             total_monthly_value_crore, total_ytd_value_crore
    Preferred view for monthly data queries - already has country names and HS descriptions
    IMPORTANT: chapter is TEXT derived from LEFT(hs_code,2), always compare as string: chapter = '85' NOT chapter = 85

11. v_quarterly_exports - Quarterly aggregations (VIEW)
    Columns: hs_code, country_code, year, quarter (Q1-Q4), quarter_num,
             quarterly_export_crore, prev_quarterly_export_crore, quarterly_growth_pct,
             months_in_quarter
    Use for quarterly comparisons e.g. "Q1 vs Q2"

12. v_hs_codes_complete - Complete HS code information
    Columns: hs_code (VARCHAR), description, chapter_number (VARCHAR - use quotes e.g. chapter_number = '85'), code_level, overall_status
    IMPORTANT: chapter_number is VARCHAR, always compare as string: chapter_number = '85' NOT chapter_number = 85

13. countries - Country information
    Columns: country_code (AUS, UAE, GBR), country_name, region

14. mv_hs_export_summary - Aggregated export statistics
    Columns: hs_code, description, export_countries_count, total_export_value_crore, latest_year

Functions:
- get_export_feasibility(hs_code VARCHAR, country_code VARCHAR) - Check export feasibility
- search_hs_codes(search_term TEXT) - Search HS codes by description

Important:
- Country codes: 'AUS' (Australia), 'UAE' (United Arab Emirates), 'GBR' (United Kingdom)
- For annual data: year format is '2023-2024', '2024-2025' in export_statistics
- For monthly data: use monthly_export_statistics or v_monthly_exports (year=2024, month=1-12)
- Export values are always in ₹ Crore
- To get full policy details for an HS code with references, JOIN v_export_policy_unified or query itc_chapter_policies
- For "what are prohibited items" queries, use: SELECT * FROM prohibited_items
- For "what are restricted items" queries, use: SELECT * FROM restricted_items
- For "what are STE items" queries, use: SELECT * FROM ste_items
- For monthly/trend/seasonal queries, prefer v_monthly_exports (has names) or v_quarterly_exports
"""
        
        self.sql_prompt = ChatPromptTemplate.from_messages([
            ("system", f"""You are a SQL expert for an export database.

{self.schema_context}

Generate SQL queries to answer user questions.
Return ONLY the SQL query, no explanations.
Use proper PostgreSQL syntax.
Always include LIMIT clauses for safety (LIMIT 50 by default).

IMPORTANT: Use conversation history below to resolve references.
If user says "it", "that", "same code", etc., find what HS code/country
they referred to in previous messages and use that."""),
            MessagesPlaceholder(variable_name="messages"),
            ("human", "Generate a SQL query for: {query}")
        ])
    
    def execute(self, state: AgentState) -> AgentState:
        """Execute SQL query"""
        try:
            # Generate SQL (with conversation history for context)
            sql_query = (self.sql_prompt | self.llm | StrOutputParser()).invoke({
                "messages": state["messages"],
                "query": state["user_query"]
            })
            
            # Clean up SQL query
            sql_query = sql_query.strip()
            sql_query = re.sub(r'^```sql\n?', '', sql_query)
            sql_query = re.sub(r'\n?```$', '', sql_query)
            
            # Execute query using psycopg2
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()
            cursor.execute(sql_query)
            
            # Fetch results
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                result = {"columns": columns, "rows": rows}
            else:
                result = {"affected_rows": cursor.rowcount}
            
            cursor.close()
            conn.close()
            
            state["sql_results"] = {
                "query": sql_query,
                "result": result,
                "success": True
            }
            
            state["sources"].append({
                "type": "sql",
                "query": sql_query,
                "database": Config.DB_CONFIG['database'],
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            state["sql_results"] = {
                "query": sql_query if 'sql_query' in locals() else None,
                "error": str(e),
                "success": False
            }
        
        state["next_agent"] = "synthesizer"
        return state


class PolicyAgent:
    """Agent for checking export policies and restrictions"""
    
    def __init__(self):
        self.integrator = ExportDataIntegrator(use_vector_stores=False)
    
    def execute(self, state: AgentState) -> AgentState:
        """Check export policy"""
        hs_code = state.get("hs_code")
        country = state.get("country")
        
        if not hs_code:
            state["policy_results"] = {
                "error": "No HS code provided",
                "success": False
            }
            state["next_agent"] = "synthesizer"
            return state
        
        try:
            # Get comprehensive export check
            if country:
                result = self.integrator.can_export_to_country(
                    hs_code=hs_code,
                    country=country,
                    check_agreements=False
                )
            else:
                result = self.integrator.get_hs_code_info(hs_code)
            
            state["policy_results"] = {
                "result": result,
                "success": True
            }
            
            state["sources"].append({
                "type": "policy_check",
                "hs_code": hs_code,
                "country": country,
                "tables": ["v_export_policy_unified", "prohibited_items", "restricted_items", "ste_items"],
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            state["policy_results"] = {
                "error": str(e),
                "success": False
            }
        
        state["next_agent"] = "synthesizer"
        return state


class VectorAgent:
    """Agent for searching agreements and policies using vector search"""
    
    def __init__(self):
        self.integrator = ExportDataIntegrator(use_vector_stores=True)
    
    def execute(self, state: AgentState) -> AgentState:
        """Search vector stores"""
        try:
            results = []
            
            # Search agreements
            if self.integrator.agreements_retriever:
                agreement_results = self.integrator.search_trade_agreements(
                    query=state["user_query"],
                    country=state.get("country"),
                    top_k=3
                )
                
                for doc in agreement_results:
                    results.append({
                        "type": "agreement",
                        "text": doc["text"],
                        "metadata": doc["metadata"],
                        "score": doc["similarity_score"]
                    })
            
            state["vector_results"] = results
            
            # Add sources
            if results:
                state["sources"].append({
                    "type": "vector_search",
                    "store": "agreements_chromadb",
                    "num_results": len(results),
                    "query": state["user_query"],
                    "timestamp": datetime.now().isoformat()
                })
            
        except Exception as e:
            state["vector_results"] = []
            state["sources"].append({
                "type": "vector_search_error",
                "error": str(e)
            })
        
        state["next_agent"] = "synthesizer"
        return state


class AgreementsAgent:
    """Agent for searching trade agreements with cross-reference resolution.
    
    Searches the ingested trade agreement PDFs (India-Australia ECTA, India-UAE CEPA,
    India-UK CETA) using FAISS/ChromaDB vector search. Returns relevant articles,
    rules of origin, tariff provisions, customs procedures, etc.
    """
    
    def __init__(self):
        self.retriever = None
        try:
            import sys as _sys
            _sys.path.insert(0, str(Config.ROOT_DIR / "storage-scripts"))
            from agreements_retriever import AgreementsRetriever
            
            agreements_path = Config.ROOT_DIR / "agreements_rag_store"
            if agreements_path.exists():
                self.retriever = AgreementsRetriever(storage_path=agreements_path)
                print("✓ AgreementsAgent: Retriever loaded")
            else:
                print("⚠️  AgreementsAgent: agreements_rag_store not found")
        except Exception as e:
            print(f"⚠️  AgreementsAgent: Could not load retriever: {e}")
    
    def execute(self, state: AgentState) -> AgentState:
        """Search trade agreements for relevant provisions"""
        query = state["user_query"]
        country = state.get("country")
        hs_code = state.get("hs_code")
        
        if not self.retriever:
            state["agreement_results"] = []
            state["sources"].append({
                "type": "agreements_error",
                "error": "Agreements retriever not available"
            })
            state["next_agent"] = "synthesizer"
            return state
        
        try:
            results = []
            
            # Build an enriched search query for better retrieval
            search_query = query
            if hs_code:
                search_query = f"HS code {hs_code} {query}"
            
            # Primary search with cross-reference resolution
            agreement_hits = self.retriever.search(
                query=search_query,
                top_k=5,
                country=country,
                include_cross_refs=True
            )
            
            for doc in agreement_hits:
                meta = doc.get("metadata", {})
                result_entry = {
                    "type": "trade_agreement",
                    "text": doc["text"],
                    "metadata": meta,
                    "score": doc["similarity_score"],
                    "source_type": doc.get("source", "unknown"),
                    "country": meta.get("country", "unknown"),
                    "agreement": meta.get("agreement", ""),
                    "article": meta.get("article_full", ""),
                    "doc_type": meta.get("doc_type", ""),
                    "cross_ref_articles": meta.get("cross_ref_articles", ""),
                    "cross_ref_annexes": meta.get("cross_ref_annexes", ""),
                    "is_cross_ref": doc.get("source") == "cross_reference",
                }
                results.append(result_entry)
            
            state["agreement_results"] = results
            
            # Add source attribution
            if results:
                countries_found = list(set(r["country"] for r in results))
                agreements_found = list(set(r["agreement"] for r in results if r["agreement"]))
                state["sources"].append({
                    "type": "trade_agreements",
                    "store": "agreements_rag_store (FAISS + ChromaDB)",
                    "num_results": len(results),
                    "countries": countries_found,
                    "agreements": agreements_found,
                    "cross_refs_included": sum(1 for r in results if r["is_cross_ref"]),
                    "query": search_query,
                    "timestamp": datetime.now().isoformat()
                })
            
        except Exception as e:
            state["agreement_results"] = []
            state["sources"].append({
                "type": "agreements_error",
                "error": str(e)
            })
        
        state["next_agent"] = "synthesizer"
        return state


class AnswerSynthesizer:
    """Synthesizes final answer from all agent results"""
    
    def __init__(self, llm):
        self.llm = llm
        self.synthesis_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert export advisor for India.

Synthesize a comprehensive answer from the agent results provided.

Guidelines:
1. Start with a direct answer to the user's question
2. Include relevant statistics if available (from SQL results)
3. Mention any restrictions or requirements (from policy results)
4. Reference trade agreements with SPECIFIC article numbers if available (from agreement results)
5. When agreement results are provided, cite the specific articles (e.g., "Article 4.3 of AI-ECTA")
6. Mention relevant rules of origin, tariff provisions, or customs procedures from agreements
7. Be specific and cite sources
8. Format numbers properly (₹ Crore for Indian values)
9. Use emojis: ✅ for allowed, ❌ for prohibited, ⚠️ for restricted, 📜 for agreement provisions
10. Use markdown formatting for readability (headers, bold, lists, tables)

IMPORTANT: Use the conversation history to maintain context.
If the user refers to 'it', 'that code', 'same product', resolve from prior messages.

Always structure as:
- Direct Answer
- Key Details (including agreement provisions when available)
- Sources Used"""),
            MessagesPlaceholder(variable_name="messages"),
            ("human", """User Query: {query}

SQL Results: {sql_results}

Policy Results: {policy_results}

Vector Search Results: {vector_results}

Trade Agreement Results: {agreement_results}

Synthesize a comprehensive answer using markdown formatting.""")
        ])
    
    def execute(self, state: AgentState) -> AgentState:
        """Synthesize final answer"""
        
        # Prepare results for synthesis
        sql_summary = "Not available"
        if state.get("sql_results"):
            if state["sql_results"].get("success"):
                sql_summary = str(state["sql_results"]["result"])
            elif state["sql_results"].get("error"):
                sql_summary = f"Query failed: {state['sql_results']['error']}"
        
        policy_summary = "Not available"
        if state.get("policy_results") and state["policy_results"].get("success"):
            result = state["policy_results"]["result"]
            if isinstance(result, dict):
                if "can_export" in result:
                    policy_summary = f"Export Allowed: {result['can_export']}\n"
                    policy_summary += f"Issues: {result.get('issues', [])}\n"
                    policy_summary += f"Warnings: {result.get('warnings', [])}\n"
                    policy_summary += f"Requirements: {result.get('requirements', [])}"
                    # Include HS info details if available
                    hs_info = result.get('hs_info', {})
                    if hs_info.get('is_prohibited'):
                        p_info = hs_info.get('prohibited_info', {})
                        policy_summary += f"\nPROHIBITED: {p_info.get('description', 'N/A')} - {p_info.get('policy_condition', 'Export not allowed')}"
                    if hs_info.get('is_restricted'):
                        r_info = hs_info.get('restricted_info', {})
                        policy_summary += f"\nRESTRICTED: {r_info.get('description', 'N/A')} - {r_info.get('policy_condition', 'Special conditions apply')}"
                    if hs_info.get('is_ste'):
                        s_info = hs_info.get('ste_info', {})
                        policy_summary += f"\nSTE REQUIRED: Export only via {s_info.get('authorized_entity', 'designated entity')}"
                else:
                    policy_summary = f"Description: {result.get('description', 'N/A')}\n"
                    policy_summary += f"Status: Prohibited={result.get('is_prohibited')}, Restricted={result.get('is_restricted')}, STE={result.get('is_ste')}"
                    if result.get('is_prohibited'):
                        p_info = result.get('prohibited_info', {})
                        policy_summary += f"\nPROHIBITED DETAILS: {p_info.get('description', 'N/A')} - {p_info.get('policy_condition', 'Export not allowed')}"
                    if result.get('is_restricted'):
                        r_info = result.get('restricted_info', {})
                        policy_summary += f"\nRESTRICTED DETAILS: {r_info.get('description', 'N/A')} - {r_info.get('policy_condition', 'Special conditions apply')}"
                    if result.get('is_ste'):
                        s_info = result.get('ste_info', {})
                        policy_summary += f"\nSTE DETAILS: Export only via {s_info.get('authorized_entity', 'designated entity')}"
        
        vector_summary = "Not available"
        if state.get("vector_results"):
            docs = state["vector_results"][:2]
            vector_summary = "\n\n".join([
                f"Document: {d['metadata'].get('filename', 'N/A')}\nRelevance: {d['score']:.1%}\nExcerpt: {d['text'][:200]}..."
                for d in docs
            ])
        
        # Build agreement summary
        agreement_summary = "Not available"
        if state.get("agreement_results"):
            agreement_docs = state["agreement_results"]
            parts = []
            for d in agreement_docs[:4]:  # Top 4 agreement results
                article = d.get('article', 'N/A')
                agreement = d.get('agreement', 'N/A')
                country = d.get('country', 'N/A')
                doc_type = d.get('doc_type', '')
                score = d.get('score', 0)
                cross_refs = d.get('cross_ref_articles', '')
                is_xref = d.get('is_cross_ref', False)
                text_preview = d['text'][:300]
                
                entry = f"Agreement: {agreement}\n"
                entry += f"Country: {country.upper()}\n"
                if article:
                    entry += f"Article: {article}\n"
                if doc_type:
                    entry += f"Type: {doc_type}\n"
                entry += f"Relevance: {score:.1%}\n"
                if cross_refs:
                    entry += f"Cross-references: Articles {cross_refs}\n"
                if is_xref:
                    entry += "[Auto-resolved cross-reference]\n"
                entry += f"Content: {text_preview}..."
                parts.append(entry)
            
            agreement_summary = "\n\n---\n\n".join(parts)
        
        # Generate synthesis
        response = self.synthesis_prompt | self.llm | StrOutputParser()
        final_answer = response.invoke({
            "messages": state["messages"],
            "query": state["user_query"],
            "sql_results": sql_summary,
            "policy_results": policy_summary,
            "vector_results": vector_summary,
            "agreement_results": agreement_summary
        })
        
        state["final_answer"] = final_answer
        state["next_agent"] = None
        
        return state


# ========== GRAPH CONSTRUCTION ==========

class ExportAdvisoryGraph:
    """Main LangGraph orchestrator"""
    
    def __init__(self, google_api_key: Optional[str] = None):
        """Initialize the graph"""
        
        # Setup LLM
        api_key = google_api_key or Config.GOOGLE_API_KEY or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("Google API key required. Set in .env or pass as parameter.")
        
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=api_key,
            temperature=0.1
        )
        
        # Initialize agents
        self.router = QueryRouter(self.llm)
        self.sql_agent = SQLAgent(self.llm)
        self.policy_agent = PolicyAgent()
        self.vector_agent = VectorAgent()
        self.agreements_agent = AgreementsAgent()
        self.synthesizer = AnswerSynthesizer(self.llm)
        
        # Session-based conversation memory
        self.sessions: Dict[str, List[BaseMessage]] = {}
        
        # Build graph
        self.graph = self._build_graph()
    
    def _combined_execute(self, state: AgentState) -> AgentState:
        """Execute both SQL and Policy agents for complex queries"""
        # Run SQL agent first
        state = self.sql_agent.execute(state)
        
        # Run Policy agent (even without a specific HS code,
        # we do a chapter-level policy check)
        hs_code = state.get("hs_code")
        if hs_code:
            state = self.policy_agent.execute(state)
        else:
            # For chapter-level combined queries, do a batch policy check
            try:
                integrator = ExportDataIntegrator(use_vector_stores=False)
                query_lower = state["user_query"].lower()
                
                # Extract chapter numbers from query
                chapter_matches = re.findall(r'chapter\s*(\d{1,2})', query_lower)
                
                policy_data = {}
                conn = psycopg2.connect(**Config.DB_CONFIG)
                cursor = conn.cursor()
                
                for ch in chapter_matches:
                    ch_padded = ch.zfill(2)
                    
                    # Get prohibited items in this chapter
                    cursor.execute(
                        "SELECT hs_code, description, policy_condition FROM prohibited_items WHERE hs_code LIKE %s LIMIT 20",
                        (f"{ch_padded}%",)
                    )
                    prohibited = [{"hs_code": r[0], "description": r[1], "condition": r[2]} for r in cursor.fetchall()]
                    
                    # Get restricted items in this chapter
                    cursor.execute(
                        "SELECT hs_code, description, policy_condition FROM restricted_items WHERE hs_code LIKE %s LIMIT 20",
                        (f"{ch_padded}%",)
                    )
                    restricted = [{"hs_code": r[0], "description": r[1], "condition": r[2]} for r in cursor.fetchall()]
                    
                    # Get STE items in this chapter
                    cursor.execute(
                        "SELECT hs_code, description, authorized_entity, policy_condition FROM ste_items WHERE hs_code LIKE %s LIMIT 20",
                        (f"{ch_padded}%",)
                    )
                    ste = [{"hs_code": r[0], "description": r[1], "entity": r[2], "condition": r[3]} for r in cursor.fetchall()]
                    
                    # Get policy conditions for this chapter
                    cursor.execute(
                        "SELECT policy_type, policy_text FROM itc_chapter_policies WHERE chapter_code = %s ORDER BY policy_type",
                        (ch_padded,)
                    )
                    policies = [{"type": r[0], "text": r[1]} for r in cursor.fetchall()]
                    
                    policy_data[f"chapter_{ch_padded}"] = {
                        "prohibited": prohibited,
                        "restricted": restricted,
                        "ste": ste,
                        "policy_conditions": policies,
                        "prohibited_count": len(prohibited),
                        "restricted_count": len(restricted),
                        "ste_count": len(ste)
                    }
                
                cursor.close()
                conn.close()
                integrator.close()
                
                state["policy_results"] = {
                    "result": policy_data,
                    "success": True,
                    "chapters_checked": chapter_matches
                }
                
                state["sources"].append({
                    "type": "policy_check",
                    "chapters": chapter_matches,
                    "tables": ["prohibited_items", "restricted_items", "ste_items", "itc_chapter_policies"],
                    "timestamp": datetime.now().isoformat()
                })
                
            except Exception as e:
                state["policy_results"] = {
                    "error": str(e),
                    "success": False
                }
        # Also search trade agreements if country is mentioned
        country = state.get("country")
        if country and self.agreements_agent.retriever:
            state = self.agreements_agent.execute(state)
        
        state["next_agent"] = "synthesizer"
        state["query_type"] = "combined"
        return state
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow"""
        
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("router", self.router.route)
        workflow.add_node("sql", self.sql_agent.execute)
        workflow.add_node("policy", self.policy_agent.execute)
        workflow.add_node("vector", self.vector_agent.execute)
        workflow.add_node("agreements", self.agreements_agent.execute)
        workflow.add_node("combined", self._combined_execute)
        workflow.add_node("synthesizer", self.synthesizer.execute)
        
        # Set entry point
        workflow.set_entry_point("router")
        
        # Add conditional edges from router
        workflow.add_conditional_edges(
            "router",
            lambda state: state["next_agent"],
            {
                "sql": "sql",
                "policy": "policy",
                "vector": "vector",
                "agreements": "agreements",
                "combined": "combined",
                "general": "synthesizer"
            }
        )
        
        # All agents go to synthesizer
        workflow.add_edge("sql", "synthesizer")
        workflow.add_edge("policy", "synthesizer")
        workflow.add_edge("vector", "synthesizer")
        workflow.add_edge("agreements", "synthesizer")
        workflow.add_edge("combined", "synthesizer")
        
        # Synthesizer is the end
        workflow.add_edge("synthesizer", END)
        
        return workflow.compile()
    
    def query(self, user_query: str, session_id: str = "default") -> Dict[str, Any]:
        """
        Process a user query through the multi-agent system with conversation memory
        
        Args:
            user_query: Natural language query
            session_id: Session identifier for maintaining conversation history
            
        Returns:
            Dict with answer and sources
        """
        
        # Initialize session if not exists
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        
        # Add user message to session history
        self.sessions[session_id].append(HumanMessage(content=user_query))
        
        # Initialize state with full conversation history
        initial_state = {
            "messages": list(self.sessions[session_id]),  # Copy full history
            "user_query": user_query,
            "query_type": None,
            "hs_code": None,
            "country": None,
            "sql_results": None,
            "vector_results": None,
            "policy_results": None,
            "agreement_results": None,
            "final_answer": None,
            "sources": [],
            "next_agent": None
        }
        
        # Run graph
        result = self.graph.invoke(initial_state)
        
        # Add assistant response to session history
        self.sessions[session_id].append(AIMessage(content=result["final_answer"]))
        
        # Format response
        return {
            "answer": result["final_answer"],
            "sources": result["sources"],
            "query_type": result["query_type"],
            "hs_code": result.get("hs_code"),
            "country": result.get("country"),
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }
    
    def clear_session(self, session_id: str = "default") -> None:
        """Clear conversation history for a session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def get_session_history(self, session_id: str = "default") -> List[Dict[str, str]]:
        """Get conversation history for a session"""
        if session_id not in self.sessions:
            return []
        
        history = []
        for msg in self.sessions[session_id]:
            if isinstance(msg, HumanMessage):
                history.append({"role": "user", "content": msg.content})
            elif isinstance(msg, AIMessage):
                history.append({"role": "assistant", "content": msg.content})
        return history
    
    def list_sessions(self) -> List[str]:
        """List all active session IDs"""
        return list(self.sessions.keys())
    
    def get_session_message_count(self, session_id: str = "default") -> int:
        """Get number of messages in a session"""
        return len(self.sessions.get(session_id, []))
    
    def format_response(self, result: Dict[str, Any]) -> str:
        """Format response for display"""
        
        output = []
        output.append("="*70)
        output.append("EXPORT ADVISORY RESPONSE")
        output.append("="*70)
        output.append(f"\n{result['answer']}\n")
        
        if result["sources"]:
            output.append("─"*70)
            output.append("SOURCES:")
            for i, source in enumerate(result["sources"], 1):
                output.append(f"\n{i}. Type: {source['type']}")
                if source['type'] == 'sql':
                    output.append(f"   Query: {source['query']}")
                    output.append(f"   Database: {source['database']}")
                elif source['type'] == 'policy_check':
                    output.append(f"   HS Code: {source['hs_code']}")
                    output.append(f"   Country: {source['country']}")
                    output.append(f"   Tables: {', '.join(source['tables'])}")
                elif source['type'] == 'vector_search':
                    output.append(f"   Store: {source['store']}")
                    output.append(f"   Results: {source['num_results']}")
                elif source['type'] == 'trade_agreements':
                    output.append(f"   Store: {source['store']}")
                    output.append(f"   Results: {source['num_results']}")
                    output.append(f"   Countries: {', '.join(source.get('countries', []))}")
                    output.append(f"   Agreements: {', '.join(source.get('agreements', []))}")
                    if source.get('cross_refs_included'):
                        output.append(f"   Cross-refs resolved: {source['cross_refs_included']}")
        
        output.append("\n" + "="*70)
        output.append(f"Query Type: {result['query_type']}")
        if result.get('hs_code'):
            output.append(f"HS Code: {result['hs_code']}")
        if result.get('country'):
            output.append(f"Country: {result['country']}")
        output.append(f"Timestamp: {result['timestamp']}")
        output.append("="*70)
        
        return "\n".join(output)


# ========== DEMO ==========

def interactive_demo():
    """Interactive demo of the multi-agent system"""
    
    print("="*70)
    print("LANGGRAPH MULTI-AGENT EXPORT ADVISORY SYSTEM")
    print("="*70)
    print("\nInitializing agents...")
    
    try:
        graph = ExportAdvisoryGraph()
        print("✓ System ready!\n")
    except Exception as e:
        print(f"❌ Error initializing: {e}")
        print("\nMake sure you have:")
        print("1. GOOGLE_API_KEY in .env file")
        print("2. Database connection working")
        print("3. Vector stores available")
        return
    
    # Example queries
    demo_queries = [
        "What is the total export value for chapter 07 to Australia?",
        "Can I export HS 070310 to Australia?",
        "What are the tariff requirements for exporting to UAE?",
        "Show me export statistics for HS 610910",
    ]
    
    print("Demo Queries:")
    for i, q in enumerate(demo_queries, 1):
        print(f"{i}. {q}")
    
    print("\n" + "="*70)
    
    # Run demo
    for query in demo_queries[:2]:  # Run first 2 for demo
        print(f"\n{'═'*70}")
        print(f"Query: {query}")
        print(f"{'═'*70}\n")
        
        try:
            result = graph.query(query)
            print(graph.format_response(result))
        except Exception as e:
            print(f"❌ Error: {e}")
        
        input("\nPress Enter for next query...")
    
    # Interactive mode
    print("\n" + "="*70)
    print("INTERACTIVE MODE - Ask your questions!")
    print("(Type 'quit' to exit)")
    print("="*70 + "\n")
    
    while True:
        user_input = input("\nYour query: ").strip()
        
        if user_input.lower() in ['quit', 'exit', 'q']:
            print("\nGoodbye!")
            break
        
        if not user_input:
            continue
        
        try:
            result = graph.query(user_input)
            print("\n" + graph.format_response(result))
        except Exception as e:
            print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    interactive_demo()
