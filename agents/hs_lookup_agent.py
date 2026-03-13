"""
HS Lookup Agent — Searches the hs_master_8_digit table.

Multi-strategy retrieval with ranked confidence scores:
  1. Exact HS code lookup
  2. Prefix match (e.g. 6-digit matches all 8-digit children)
  3. PostgreSQL full-text search (plainto_tsquery)
  4. Top-3 longest keywords — AND ILIKE
  5. All keywords — AND ILIKE
  6. Top-5 longest keywords — OR ILIKE
  7. pg_trgm word_similarity (handles abbreviated/truncated text)

Result handling:
  • 0 matches        → needs_clarification=True, type="no_match"   → ask for more detail
  • 1 confident hit  → returns it directly (no clarification needed)
  • 2–8 matches      → needs_clarification=True, type="pick_one"   → show table, ask user to pick
  • >8 matches       → needs_clarification=True, type="too_broad"  → ask for more specific query
"""

import psycopg2
import re
from typing import Dict, List, Any, Optional
from config import Config


# ---------------------------------------------------------------------------
# Module-level helpers (used by the agent and importable independently)
# ---------------------------------------------------------------------------

def _row_to_dict(row: tuple, score: float) -> Dict:
    return {
        "hs_code":     row[0],
        "chapter":     row[1],
        "code_level":  row[2],
        "parent_code": row[3],
        "description": row[4],
        "score":       round(score, 3),
    }


def _merge(base: List[Dict], additions: List[Dict]) -> List[Dict]:
    """Append additions not already in base; update score if higher."""
    index = {r["hs_code"]: i for i, r in enumerate(base)}
    for r in additions:
        if r["hs_code"] in index:
            idx = index[r["hs_code"]]
            if r["score"] > base[idx]["score"]:
                base[idx]["score"] = r["score"]
        else:
            index[r["hs_code"]] = len(base)
            base.append(r)
    return base


def _top(results: List[Dict], n: int) -> List[Dict]:
    """Sort by score desc then code_level desc; return top-n."""
    return sorted(results, key=lambda r: (r["score"], r.get("code_level", 0)), reverse=True)[:n]


class HSLookupAgent:
    """Agent that searches the hs_master_8_digit table for HS code lookups."""

    _TRGM_THRESHOLD = 0.20  # minimum word_similarity to include a result
    _schema_cache: Optional[bool] = None  # None=unknown, True=new (has code_level), False=old

    def __init__(self):
        pass

    def _get_connection(self):
        return psycopg2.connect(**Config.DB_CONFIG)

    def _has_new_schema(self, cur) -> bool:
        """
        Check (once, then cache) whether the table has the v2 columns
        (code_level, parent_code).  Works with both old and new schema.
        """
        if HSLookupAgent._schema_cache is not None:
            return HSLookupAgent._schema_cache
        try:
            cur.execute(
                """SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'hs_master_8_digit'
                   AND column_name = 'code_level'"""
            )
            HSLookupAgent._schema_cache = cur.fetchone() is not None
        except Exception:
            HSLookupAgent._schema_cache = False
        return HSLookupAgent._schema_cache

    def _cols(self, cur) -> str:
        """Return the SELECT column list appropriate for the detected schema."""
        if self._has_new_schema(cur):
            return "hs_code, chapter, code_level, parent_code, description"
        # Old schema — inject constant placeholders so _row_to_dict still works
        return "hs_code, chapter, 3 AS code_level, NULL AS parent_code, description"

    def _order_by_level(self, cur) -> str:
        """ORDER BY clause that works with both schemas."""
        if self._has_new_schema(cur):
            return "code_level DESC, hs_code"
        return "hs_code"

    def _extract_keywords(self, query: str) -> List[str]:
        """Split on whitespace/punctuation; keep tokens ≥3 chars (no stop words); deduplicate."""
        STOP = {
            'and', 'the', 'for', 'are', 'not', 'with', 'from', 'has',
            'nes', 'nec', 'other', 'others', 'what', 'which', 'type',
            'its', 'this', 'that', 'into', 'also',
        }
        tokens = re.split(r'[\s\-,/;:()\[\]]+', query)
        seen: set = set()
        result = []
        for t in tokens:
            t = t.strip().lower()
            if len(t) >= 3 and t not in STOP and t not in seen:
                seen.add(t)
                result.append(t)
        return result

    # ------------------------------------------------------------------
    # Individual strategies — each returns List[Dict] with 'score'
    # ------------------------------------------------------------------

    def _s_exact(self, cur, hs_code: str) -> List[Dict]:
        cols = self._cols(cur)
        cur.execute(
            f"SELECT {cols} FROM hs_master_8_digit WHERE hs_code = %s",
            (hs_code,)
        )
        return [_row_to_dict(r, 1.0) for r in cur.fetchall()]

    def _s_prefix(self, cur, hs_code: str, limit: int) -> List[Dict]:
        cols  = self._cols(cur)
        order = self._order_by_level(cur)
        cur.execute(
            f"SELECT {cols} FROM hs_master_8_digit "
            f"WHERE hs_code LIKE %s ORDER BY {order} LIMIT %s",
            (f"{hs_code}%", limit)
        )
        return [_row_to_dict(r, 0.90) for r in cur.fetchall()]

    def _s_fts(self, cur, query: str, limit: int) -> List[Dict]:
        cols     = self._cols(cur)
        order_l  = ", code_level DESC" if self._has_new_schema(cur) else ""
        cur.execute(
            f"""SELECT {cols},
                      ts_rank(to_tsvector('english', description),
                              plainto_tsquery('english', %s)) AS rank
               FROM hs_master_8_digit
               WHERE to_tsvector('english', description) @@ plainto_tsquery('english', %s)
               ORDER BY rank DESC{order_l} LIMIT %s""",
            (query, query, limit)
        )
        return [_row_to_dict(r, min(float(r[5]) * 2 + 0.40, 0.95)) for r in cur.fetchall()]

    def _s_and_ilike(self, cur, keywords: List[str], limit: int) -> List[Dict]:
        if not keywords:
            return []
        cols  = self._cols(cur)
        order = self._order_by_level(cur)
        conds = " AND ".join(["description ILIKE %s"] * len(keywords))
        params = [f"%{kw}%" for kw in keywords] + [limit]
        cur.execute(
            f"SELECT {cols} FROM hs_master_8_digit WHERE {conds} ORDER BY {order} LIMIT %s",
            params
        )
        return [_row_to_dict(r, 0.65) for r in cur.fetchall()]

    def _s_or_ilike(self, cur, keywords: List[str], limit: int) -> List[Dict]:
        if not keywords:
            return []
        cols  = self._cols(cur)
        order = self._order_by_level(cur)
        conds = " OR ".join(["description ILIKE %s"] * len(keywords))
        params = [f"%{kw}%" for kw in keywords] + [limit]
        cur.execute(
            f"SELECT {cols} FROM hs_master_8_digit WHERE {conds} ORDER BY {order} LIMIT %s",
            params
        )
        return [_row_to_dict(r, 0.45) for r in cur.fetchall()]

    def _s_trgm(self, cur, query: str, limit: int) -> List[Dict]:
        try:
            cols = self._cols(cur)
            cur.execute(
                f"""SELECT {cols},
                          word_similarity(%s, description) AS sim
                   FROM hs_master_8_digit
                   WHERE word_similarity(%s, description) > %s
                   ORDER BY sim DESC LIMIT %s""",
                (query, query, self._TRGM_THRESHOLD, limit)
            )
            return [_row_to_dict(r, min(float(r[5]) + 0.10, 0.85)) for r in cur.fetchall()]
        except Exception:
            return []

    def _s_itc_products(self, cur, query: str, keywords: List[str], limit: int) -> List[Dict]:
        """
        Supplemental search against itc_hs_products (2,006 ITC-specific codes,
        Chapters 7, 8, 61, 62, 85, 90) which also carries export_policy data.
        Normalises rows into the same shape as _row_to_dict output.
        """
        results: List[Dict] = []

        def _itc_row(r, score: float) -> Dict:
            try:
                chapter = int(str(r[1]).strip()) if r[1] else 0
            except (ValueError, TypeError):
                chapter = 0
            try:
                code_level = int(r[2]) if r[2] is not None else 3
            except (ValueError, TypeError):
                code_level = 3
            return {
                "hs_code":     r[0],
                "chapter":     chapter,
                "code_level":  code_level,
                "parent_code": r[3],
                "description": r[4],
                "score":       round(score, 3),
            }

        # FTS on description
        try:
            cur.execute(
                """SELECT hs_code, chapter_code, level, parent_hs_code, description,
                          ts_rank(to_tsvector('english', description),
                                  plainto_tsquery('english', %s)) AS rank
                   FROM itc_hs_products
                   WHERE to_tsvector('english', description) @@ plainto_tsquery('english', %s)
                   ORDER BY rank DESC LIMIT %s""",
                (query, query, limit)
            )
            for r in cur.fetchall():
                results.append(_itc_row(r, min(float(r[5]) * 2 + 0.35, 0.90)))
        except Exception:
            pass

        # ILIKE fallback (top-3 longest keywords)
        if not results and keywords:
            top_kws = sorted(keywords, key=len, reverse=True)[:3]
            conds = " AND ".join(["description ILIKE %s"] * len(top_kws))
            try:
                cur.execute(
                    f"SELECT hs_code, chapter_code, level, parent_hs_code, description"
                    f" FROM itc_hs_products WHERE {conds} ORDER BY hs_code LIMIT %s",
                    [f"%{kw}%" for kw in top_kws] + [limit]
                )
                for r in cur.fetchall():
                    results.append(_itc_row(r, 0.55))
            except Exception:
                pass

        return results

    # ------------------------------------------------------------------
    # Public search methods
    # ------------------------------------------------------------------

    def search_by_code(self, hs_code: str, limit: int = 20) -> List[Dict]:
        """Search by exact or prefix HS code."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            results = self._s_exact(cur, hs_code)
            if not results:
                results = self._s_prefix(cur, hs_code, limit)
            return results
        finally:
            cur.close(); conn.close()

    def search_by_description(self, query: str, limit: int = 20) -> List[Dict]:
        """
        Cascading description search across hs_master_8_digit AND itc_hs_products.
        Returns merged, ranked list.
        """
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            results: List[Dict] = []
            kws = self._extract_keywords(query)

            # hs_master_8_digit strategies (cascade — stop adding master results when enough)
            results = _merge(results, self._s_fts(cur, query, limit))
            if len(results) < 3:
                results = _merge(results, self._s_and_ilike(cur, sorted(kws, key=len, reverse=True)[:3], limit))
            if len(results) < 2:
                results = _merge(results, self._s_and_ilike(cur, kws, limit))
            if not results:
                results = _merge(results, self._s_or_ilike(cur, sorted(kws, key=len, reverse=True)[:5], limit))
            if not results:
                results = _merge(results, self._s_trgm(cur, query, limit))

            # Always supplement with itc_hs_products (ITC-specific codes + export policy)
            results = _merge(results, self._s_itc_products(cur, query, kws, limit))

            return _top(results, limit)
        finally:
            cur.close(); conn.close()

    def search_by_similarity(self, query: str, threshold: float = 0.20, limit: int = 20) -> List[Dict]:
        """Trigram word_similarity search. Kept for backward compatibility."""
        conn = self._get_connection()
        cur = conn.cursor()
        try:
            return self._s_trgm(cur, query, limit)
        finally:
            cur.close(); conn.close()

    def _merge_results(self, base: List[Dict], additions: List[Dict]) -> List[Dict]:
        """Backward-compatible merge helper."""
        return _merge(base, additions)

    def search(self, query: str, limit: int = 20) -> List[Dict]:
        """Auto-detect: route to code or description search."""
        query = query.strip()
        if re.match(r'^\d{4,8}$', query):
            return self.search_by_code(query, limit)
        return self.search_by_description(query, limit)

    # ------------------------------------------------------------------
    # LangGraph node
    # ------------------------------------------------------------------

    def execute(self, state: Dict) -> Dict:
        """
        LangGraph agent node.

        Steps:
          1. Exact/prefix lookup if an HS code is already in state
          2. Description search on LLM-expanded product_name
          3. Trigram supplement on raw user_query (handles abbreviated DB text)
          4. Classify result count → set needs_clarification + clarification_type

        Clarification types:
          "no_match"  — 0 results; ask for more detail / alternative name
          "pick_one"  — 2–8 results; show table, ask user to pick
          "too_broad" — >8 results; ask for more specific query
          None        — 1 confident result; no clarification needed
        """
        user_query   = state.get("user_query", "")
        hs_code      = state.get("hs_code")
        product_name = state.get("product_name") or ""

        results: List[Dict] = []
        search_term = ""

        # ── Step 1: HS code direct lookup ────────────────────────────
        if hs_code:
            search_term = hs_code
            results = self.search_by_code(hs_code)

        # ── Step 2: Description search on product_name ───────────────
        if not results and product_name:
            search_term = product_name
            results = _merge(results, self.search_by_description(product_name, limit=20))

        # ── Step 3: Trigram supplement on raw user_query ─────────────
        conn = self._get_connection()
        cur  = conn.cursor()
        try:
            trgm = self._s_trgm(cur, user_query, 20)
        finally:
            cur.close(); conn.close()

        results = _merge(results, trgm)
        if not search_term:
            search_term = user_query

        # ── Step 4: Raw description fallback ─────────────────────────
        if not results:
            results = self.search_by_description(user_query, limit=20)
            if not search_term:
                search_term = user_query

        results = _top(results, 20)
        count   = len(results)

        # ── Classify result ───────────────────────────────────────────
        if count == 0:
            needs_clarification = True
            clarification_type  = "no_match"
            clarification_message = (
                f"I couldn't find any HS codes matching **{search_term}**. "
                "Could you provide more detail?\n\n"
                "- Full product name (e.g. *'fresh onions and shallots'*)\n"
                "- Chapter/heading if known (e.g. *'Chapter 07'*)\n"
                "- Alternative names or trade names\n\n"
                "ℹ️ This system covers Chapters 7, 8, 61, 62, 85, and 90."
            )
        elif count == 1 and results[0]["score"] >= 0.70:
            needs_clarification = True   # still ask user to confirm
            clarification_type  = "confirm_one"
            clarification_message = (
                f"I found **one likely match** for **{search_term}**. "
                "Please confirm this is the correct product before I check export rules."
            )
        elif 1 < count <= 8:
            needs_clarification = True
            clarification_type  = "pick_one"
            clarification_message = (
                f"I found **{count} possible HS codes** for **{search_term}**. "
                "Please confirm which one matches your product:"
            )
        else:
            needs_clarification = True
            clarification_type  = "too_broad"
            clarification_message = (
                f"Your query returned **{count} matching HS codes** — too many to list usefully. "
                "Please be more specific:\n\n"
                "- Specific variety or form (e.g. *'fresh garlic'* vs *'dried garlic'*)\n"
                "- Material composition (e.g. *'cotton t-shirts'* vs *'synthetic t-shirts'*)\n"
                "- End use or trade category\n"
            )

        state["hs_lookup_results"] = {
            "results":               results,
            "count":                 count,
            "search_term":           search_term,
            "needs_clarification":   needs_clarification,
            "clarification_type":    clarification_type,
            "clarification_message": clarification_message,
            "success":               True,
            # Keep is_ambiguous for backward compatibility
            "is_ambiguous": count > 1,
        }

        state.setdefault("sources", []).append({
            "type":               "hs_master_lookup",
            "table":              "hs_master_8_digit",
            "search_term":        search_term,
            "matches_found":      count,
            "needs_clarification": needs_clarification,
        })

        return state

