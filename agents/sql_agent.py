"""
SQL Agent

Text-to-SQL agent that generates and executes PostgreSQL queries against the
export database. Uses conversation history for contextual reference resolution.
"""

import re
from datetime import datetime

import psycopg2
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser

from config import Config
from .state import AgentState
from .trade_guard import is_explicit_trade_data_request, validate_trade_hs_request
from prompts.sql_prompt import SQL_SYSTEM_PROMPT, SQL_HUMAN_TEMPLATE


class SQLAgent:
    """Text-to-SQL agent for database queries"""
    
    def __init__(self, llm):
        self.llm = llm
        self.db_config = Config.DB_CONFIG
        
        self.sql_prompt = ChatPromptTemplate.from_messages([
            ("system", SQL_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="messages"),
            ("human", SQL_HUMAN_TEMPLATE)
        ])
    
    def execute(self, state: AgentState) -> AgentState:
        """Execute SQL query"""
        user_query = state.get("user_query", "")

        if is_explicit_trade_data_request(user_query):
            validation = validate_trade_hs_request(
                query=user_query,
                state_hs_code=state.get("hs_code"),
                allowed_hs6=Config.FOCUS_HS_CODES,
            )
            if validation.status != "ok":
                state["sql_results"] = {
                    "query": None,
                    "result": {"message": validation.message},
                    "success": True,
                    "guarded": True,
                    "guard_status": validation.status,
                }
                state["sources"].append({
                    "type": "trade_data_guard",
                    "status": validation.status,
                    "message": validation.message,
                    "timestamp": datetime.now().isoformat(),
                })
                state["next_agent"] = "synthesizer"
                return state

            query_for_sql = user_query
            if validation.hs_code_6:
                query_for_sql = (
                    f"{user_query}\n\n"
                    f"Use HS code {validation.hs_code_6} for trade data tables."
                )
        else:
            query_for_sql = user_query

        try:
            # Generate SQL (with conversation history for context)
            sql_query = (self.sql_prompt | self.llm | StrOutputParser()).invoke({
                "messages": state["messages"],
                "query": query_for_sql
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
