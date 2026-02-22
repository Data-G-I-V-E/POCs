"""
Query Router

Routes user queries to the appropriate specialized agent using LLM classification.
Extracts HS code and country entities from the query.
"""

import re
from typing import Optional

import psycopg2
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser

from config import Config
from .state import AgentState
from prompts.router_prompt import ROUTER_SYSTEM_PROMPT, ROUTER_HUMAN_TEMPLATE


class QueryRouter:
    """Routes queries to appropriate agents"""
    
    def __init__(self, llm):
        self.llm = llm
        self.routing_prompt = ChatPromptTemplate.from_messages([
            ("system", ROUTER_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="messages"),
            ("human", ROUTER_HUMAN_TEMPLATE)
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
