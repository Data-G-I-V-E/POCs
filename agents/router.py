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
            
            # Search in STE items
            cursor.execute("""
                SELECT hs_code, description 
                FROM ste_items 
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
        
        # Extract query type from LLM response (format: "ROUTE_TYPE | PRODUCT: name")
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
        
        # Extract product name from LLM response (PRODUCT: <name>)
        product_name = None
        product_match = re.search(r'PRODUCT:\s*(.+)', result, re.IGNORECASE)
        if product_match:
            extracted = product_match.group(1).strip().strip('"\'')
            if extracted.upper() != "NONE" and len(extracted) > 1:
                product_name = extracted
        
        # Extract HS code and country
        query_lower = state["user_query"].lower()
        hs_match = re.search(r'\b(\d{6,8})\b', state["user_query"])
        hs_code = hs_match.group(1) if hs_match else None
        
        # If no HS code found by regex, use LLM-extracted product name to search DB
        if not hs_code and product_name:
            hs_code = self._find_hs_code_by_description(product_name)
            # If we found an HS code by description, re-route to policy
            # since the user is clearly asking about a specific product
            if hs_code and query_type in ("general", "vector"):
                query_type = "policy"
        
        country = None
        for c in Config.TARGET_COUNTRIES:
            if c in query_lower:
                country = c
                break
        
        # ── Auto-upgrade to COMBINED for comprehensive answers ──
        # When we have both a product (HS code) and a country, the user
        # almost certainly wants trade stats + policy + agreements + DGFT FTP
        # all at once — not just one slice.
        if hs_code and country and query_type in ("policy", "sql"):
            query_type = "combined"
        # Even without a country, if we have an HS code and it was routed
        # to just 'policy', upgrade to 'combined' so trade stats are included
        elif hs_code and query_type == "policy":
            query_type = "combined"
        
        state["query_type"] = query_type
        state["hs_code"] = hs_code
        state["country"] = country
        state["next_agent"] = query_type
        
        return state
