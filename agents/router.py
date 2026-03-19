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
from .trade_guard import is_explicit_trade_data_request, is_ftp_policy_reference_query
from prompts.router_prompt import ROUTER_SYSTEM_PROMPT, ROUTER_HUMAN_TEMPLATE


class QueryRouter:
    """Routes queries to appropriate agents"""
    
    def __init__(self, llm):
        self.llm = llm
        self._last_hs_matches = []
        self.routing_prompt = ChatPromptTemplate.from_messages([
            ("system", ROUTER_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="messages"),
            ("human", ROUTER_HUMAN_TEMPLATE)
        ])

    @staticmethod
    def _normalize_hs_code(hs_code: Optional[str]) -> Optional[str]:
        """Normalize HS code to digit-only format and restore missing leading zero when needed."""
        if hs_code is None:
            return None

        digits = re.sub(r"\D", "", str(hs_code))
        if not digits:
            return None

        # If chapter-leading zero is dropped (e.g., 1023900 for 01023900), restore it.
        if len(digits) in (1, 3, 5, 7):
            digits = digits.zfill(len(digits) + 1)

        if len(digits) > 8:
            digits = digits[:8]

        return digits

    def _search_policy_tables_by_description(self, query: str, limit: int = 20):
        """
        Search restricted/prohibited/STE tables by product description and return
        normalized HS matches with scores.
        """
        conn = None
        cursor = None
        try:
            conn = psycopg2.connect(**Config.DB_CONFIG)
            cursor = conn.cursor()

            # Primary: full-text search on policy descriptions
            fts_query = """
                SELECT hs_code, description, source, score
                FROM (
                    SELECT hs_code, description, 'restricted_items' AS source,
                           ts_rank(to_tsvector('english', COALESCE(description, '')),
                                   plainto_tsquery('english', %s)) AS score
                    FROM restricted_items
                    WHERE to_tsvector('english', COALESCE(description, '')) @@ plainto_tsquery('english', %s)

                    UNION ALL

                    SELECT hs_code, description, 'prohibited_items' AS source,
                           ts_rank(to_tsvector('english', COALESCE(description, '')),
                                   plainto_tsquery('english', %s)) AS score
                    FROM prohibited_items
                    WHERE to_tsvector('english', COALESCE(description, '')) @@ plainto_tsquery('english', %s)

                    UNION ALL

                    SELECT hs_code, description, 'ste_items' AS source,
                           ts_rank(to_tsvector('english', COALESCE(description, '')),
                                   plainto_tsquery('english', %s)) AS score
                    FROM ste_items
                    WHERE to_tsvector('english', COALESCE(description, '')) @@ plainto_tsquery('english', %s)
                ) ranked
                WHERE score > 0
                ORDER BY score DESC, length(hs_code) DESC, hs_code
                LIMIT %s
            """

            cursor.execute(
                fts_query,
                (query, query, query, query, query, query, limit),
            )
            rows = cursor.fetchall()

            # Fallback: keyword ILIKE when FTS returns nothing
            if not rows:
                stop_words = {
                    "and", "the", "for", "with", "from", "any", "all", "show", "tell",
                    "check", "about", "export", "exports", "can", "i", "to", "on", "of",
                    "what", "are", "is", "there", "item", "items", "policy", "rules",
                    "restriction", "restrictions", "restricted", "prohibited", "ste"
                }
                keywords = [
                    token for token in re.split(r"[\s\-,/;:()\[\]]+", query.lower())
                    if len(token) >= 3 and token not in stop_words and not token.isdigit()
                ]
                keywords = sorted(set(keywords), key=len, reverse=True)[:3]

                if keywords:
                    like_conds = " OR ".join(["description ILIKE %s"] * len(keywords))
                    like_params = [f"%{kw}%" for kw in keywords]

                    ilike_query = f"""
                        SELECT hs_code, description, source, score
                        FROM (
                            SELECT hs_code, description, 'restricted_items' AS source, 0.85 AS score
                            FROM restricted_items
                            WHERE {like_conds}

                            UNION ALL

                            SELECT hs_code, description, 'prohibited_items' AS source, 0.83 AS score
                            FROM prohibited_items
                            WHERE {like_conds}

                            UNION ALL

                            SELECT hs_code, description, 'ste_items' AS source, 0.80 AS score
                            FROM ste_items
                            WHERE {like_conds}
                        ) ranked
                        ORDER BY score DESC, length(hs_code) DESC, hs_code
                        LIMIT %s
                    """

                    cursor.execute(
                        ilike_query,
                        tuple(like_params + like_params + like_params + [limit]),
                    )
                    rows = cursor.fetchall()

            dedup = {}
            for hs_code, description, source, score in rows:
                normalized = self._normalize_hs_code(hs_code)
                if not normalized:
                    continue
                chapter = int(normalized[:2]) if len(normalized) >= 2 else 0
                code_level = 3 if len(normalized) >= 8 else 2 if len(normalized) >= 6 else 1

                entry = {
                    "hs_code": normalized,
                    "chapter": chapter,
                    "code_level": code_level,
                    "parent_code": normalized[:-2] if len(normalized) > 2 else None,
                    "description": description,
                    "score": float(score),
                    "source": source,
                }

                existing = dedup.get(normalized)
                if existing is None or entry["score"] > existing["score"]:
                    dedup[normalized] = entry

            return sorted(
                dedup.values(),
                key=lambda r: (r.get("score", 0), r.get("code_level", 0)),
                reverse=True
            )[:limit]

        except Exception as e:
            print(f"Error searching policy tables for HS code: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    
    def _find_hs_code_by_description(self, query: str) -> Optional[str]:
        """
        Find HS code by searching product descriptions.
        Delegates to HSLookupAgent which searches hs_master_8_digit (12K codes)
        and itc_hs_products (2K ITC-specific codes) with ranked results.
        Stores all matches in self._last_hs_matches for ambiguity handling.
        """
        self._last_hs_matches = []

        hs_results = []
        try:
            from .hs_lookup_agent import HSLookupAgent
            hs_results = HSLookupAgent().search_by_description(query, limit=20)
        except Exception as e:
            print(f"Error searching for HS code: {e}")

        policy_results = self._search_policy_tables_by_description(query, limit=20)

        merged = []
        index = {}
        # Prefer policy-table hits first for restriction/prohibition workflows.
        for row in policy_results + hs_results:
            normalized = self._normalize_hs_code(row.get("hs_code"))
            if not normalized:
                continue

            entry = dict(row)
            entry["hs_code"] = normalized
            entry.setdefault("description", "")
            if "chapter" not in entry:
                entry["chapter"] = int(normalized[:2]) if len(normalized) >= 2 else 0
            entry.setdefault("code_level", 3 if len(normalized) >= 8 else 2 if len(normalized) >= 6 else 1)
            entry.setdefault("parent_code", normalized[:-2] if len(normalized) > 2 else None)
            entry.setdefault("score", 0.5)

            if normalized in index:
                idx = index[normalized]
                if entry.get("score", 0) > merged[idx].get("score", 0):
                    merged[idx] = entry
            else:
                index[normalized] = len(merged)
                merged.append(entry)

        if merged:
            merged = sorted(
                merged,
                key=lambda r: (r.get("score", 0), r.get("code_level", 0)),
                reverse=True
            )
            self._last_hs_matches = merged
            return merged[0]["hs_code"]

        return None
    
    def route(self, state: AgentState) -> AgentState:
        """Route the query to appropriate agent"""
        # Reset per-query lookup cache to avoid leaking stale HS matches across turns.
        self._last_hs_matches = []

        user_query = state["user_query"]
        query_lower = user_query.lower()
        is_trade_data_request = is_explicit_trade_data_request(user_query)
        is_ftp_reference_query = is_ftp_policy_reference_query(user_query)

        response = self.routing_prompt | self.llm | StrOutputParser()
        result = response.invoke({
            "messages": state["messages"],
            "query": user_query
        })
        
        # Extract query type from LLM response (format: "ROUTE_TYPE | PRODUCT: name")
        result_upper = result.upper()
        if "COMBINED" in result_upper:
            query_type = "combined"
        elif "SQL" in result_upper:
            query_type = "sql"
        elif "HS_LOOKUP" in result_upper:
            query_type = "hs_lookup"
        elif "POLICY" in result_upper:
            query_type = "policy"
        elif "AGREEMENT" in result_upper:
            query_type = "agreements"
        elif "VECTOR" in result_upper:
            query_type = "vector"
        else:
            query_type = "general"

        # Deterministic override: DGFT FTP article/section/chapter references are
        # policy-document retrieval queries, not trade-data queries.
        if is_ftp_reference_query and not is_trade_data_request:
            query_type = "vector"
        
        # Extract product name from LLM response (PRODUCT: <name>)
        product_name = None
        product_match = re.search(r'PRODUCT:\s*(.+)', result, re.IGNORECASE)
        if product_match:
            extracted = product_match.group(1).strip().strip('"\'')
            if extracted.upper() != "NONE" and len(extracted) > 1:
                product_name = extracted

        if is_ftp_reference_query and not is_trade_data_request:
            product_name = None
        
        # Extract HS code and country
        hs_match = re.search(r'\b(\d{6,8})\b', user_query)
        hs_code = self._normalize_hs_code(hs_match.group(1)) if hs_match else None
        
        # If no HS code in current query, scan conversation history for the most
        # recently mentioned HS code — but ONLY for follow-up queries about the
        # same product, NOT when the user is asking about a new product.
        # Skip history scan for hs_lookup (new classification request) and when
        # the query contains a new product name to look up.
        _is_new_product_query = (
            query_type == "hs_lookup"
            or bool(product_name)
            or (is_ftp_reference_query and not is_trade_data_request)
        )
        if not hs_code and not _is_new_product_query:
            for msg in reversed(state.get("messages", [])[:-1]):
                content = msg.content if hasattr(msg, "content") else str(msg)
                m = re.search(r'\b(\d{6,8})\b', content)
                if m:
                    hs_code = self._normalize_hs_code(m.group(1))
                    break
        
        # If still no HS code found, use LLM-extracted product name to search DB
        if not hs_code and product_name and not (is_ftp_reference_query and not is_trade_data_request):
            hs_code = self._find_hs_code_by_description(product_name)
            # If we found an HS code by description, re-route to policy
            # since the user is clearly asking about a specific product
            if hs_code and query_type in ("general", "vector"):
                query_type = "policy"

        if is_ftp_reference_query and not is_trade_data_request:
            hs_code = None
        
        country = None
        for c in Config.TARGET_COUNTRIES:
            if c in query_lower:
                country = c
                break
        
        # ── Auto-upgrade to COMBINED for comprehensive answers ──
        # When we have both a product (HS code) and a country, the user
        # almost certainly wants trade stats + policy + agreements + DGFT FTP
        # all at once — not just one slice.
        # hs_lookup is exempt: user just wants the classification table.
        if query_type != "hs_lookup":
            if hs_code and country and query_type in ("policy", "sql"):
                query_type = "combined"
            elif hs_code and query_type == "policy":
                query_type = "combined"

        # ── Post-HS-lookup follow-up upgrade ──
        # If the user just finished a HS lookup flow and is now asking about
        # restrictions / export rules / policy — route to combined so the
        # policy + SQL + agreements agents all fire.
        POLICY_FOLLOWUP_KEYWORDS = [
            'restriction', 'restrict', 'prohibited', 'ban', 'allowed',
            'can i export', 'export rule', 'policy', 'regulation',
            'requirement', 'documentation', 'certificate', 'license',
            'take care', 'should know', 'what do i need', 'tariff',
            'duty', 'compliance', 'condition', 'ste', 'state trading',
        ]
        if hs_code and query_type in ("hs_lookup", "general"):
            if any(kw in query_lower for kw in POLICY_FOLLOWUP_KEYWORDS):
                query_type = "combined" if country else "combined"
                print(f"[Router] Post-hs_lookup upgrade: '{query_type}' for HS {hs_code}")
        
        state["query_type"] = query_type
        state["hs_code"] = hs_code
        state["country"] = country
        state["product_name"] = product_name
        state["next_agent"] = query_type
        
        # Store HS master matches for ambiguity handling
        if hasattr(self, '_last_hs_matches') and self._last_hs_matches:
            state["hs_lookup_results"] = {
                "results": self._last_hs_matches,
                "count": len(self._last_hs_matches),
                "search_term": product_name or hs_code or "",
                "is_ambiguous": len(self._last_hs_matches) > 3,
                "success": True
            }
        
        return state
