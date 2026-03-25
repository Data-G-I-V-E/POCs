"""
Answer Synthesizer

Combines results from all agents (SQL, Policy, Vector, Agreements) into a
coherent, markdown-formatted response with source citations.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser

from .state import AgentState
from prompts.synthesizer_prompt import SYNTHESIZER_SYSTEM_PROMPT, SYNTHESIZER_HUMAN_TEMPLATE


class AnswerSynthesizer:
    """Synthesizes final answer from all agent results"""
    
    def __init__(self, llm):
        self.llm = llm
        self.synthesis_prompt = ChatPromptTemplate.from_messages([
            ("system", SYNTHESIZER_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="messages"),
            ("human", SYNTHESIZER_HUMAN_TEMPLATE)
        ])
    
    def execute(self, state: AgentState) -> AgentState:
        """Synthesize final answer"""
        
        # Prepare results for synthesis
        sql_summary = "NOT CHECKED — SQL agent was not invoked for this query."
        if state.get("sql_results"):
            if state["sql_results"].get("success"):
                result = state["sql_results"]["result"]
                if isinstance(result, dict) and "columns" in result and "rows" in result:
                    columns = result["columns"]
                    rows = result["rows"]
                    if rows:
                        # Format as a readable markdown table for the LLM
                        header = " | ".join(str(c) for c in columns)
                        separator = " | ".join("---" for _ in columns)
                        data_rows = "\n".join(
                            " | ".join(str(v) for v in row)
                            for row in rows[:50]  # cap at 50 rows to avoid prompt overflow
                        )
                        sql_summary = f"Query returned {len(rows)} rows.\n\n| {header} |\n| {separator} |\n"
                        sql_summary += "\n".join(f"| {' | '.join(str(v) for v in row)} |" for row in rows[:50])
                        if len(rows) > 50:
                            sql_summary += f"\n... and {len(rows) - 50} more rows."
                    else:
                        sql_summary = "Query executed successfully but returned 0 rows."
                else:
                    sql_summary = str(result)
            elif state["sql_results"].get("error"):
                sql_summary = f"Query failed: {state['sql_results']['error']}"
        
        policy_summary = "NOT CHECKED — Policy agent was not invoked for this query."
        if state.get("policy_results"):
            if state["policy_results"].get("success"):
                result = state["policy_results"]["result"]
                if isinstance(result, dict):
                    # Helper: build restriction detail from a info dict using policy_condition column
                    def _restriction_detail(info: dict) -> str:
                        cond = (info.get('policy_condition') or '').strip()
                        desc = (info.get('description') or 'N/A').strip()
                        return f"{desc} — {cond}" if cond else desc

                    # Resolve the actual flags/info regardless of path (can_export vs get_hs_code_info)
                    if "can_export" in result:
                        hs_info = result.get('hs_info', {})
                        is_prohibited = hs_info.get('is_prohibited', False)
                        is_restricted  = hs_info.get('is_restricted', False)
                        is_ste         = hs_info.get('is_ste', False)
                        prohibited_info = hs_info.get('prohibited_info', {})
                        restricted_info = hs_info.get('restricted_info', {})
                        ste_info        = hs_info.get('ste_info', {})
                        chapter_notes   = hs_info.get('chapter_notes', {})
                        itc_policy      = hs_info.get('itc_policy', {})
                        policy_summary  = f"Export Allowed: {result['can_export']}\n"
                        if result.get('issues'):
                            policy_summary += f"Issues: {result['issues']}\n"
                        if result.get('warnings'):
                            policy_summary += f"Warnings: {result['warnings']}\n"
                        if result.get('requirements'):
                            policy_summary += f"Requirements: {result['requirements']}\n"
                        if itc_policy:
                            itc_pol_val = (itc_policy.get('itc_policy') or '').strip()
                            notif_no    = (itc_policy.get('itc_notification') or '').strip()
                            notif_date  = itc_policy.get('itc_date', '')
                            overall     = (itc_policy.get('overall_status') or '').strip()
                            ref_text    = (itc_policy.get('policy_reference_text') or '').strip()
                            if itc_pol_val:
                                policy_summary += f"ITC-HS Policy: {itc_pol_val}\n"
                            if overall:
                                policy_summary += f"Overall Status: {overall}\n"
                            if notif_no:
                                date_str = f" dated {notif_date}" if notif_date else ""
                                policy_summary += f"ITC Notification: {notif_no}{date_str}\n"
                            if ref_text:
                                policy_summary += f"Policy Reference Text: {ref_text}\n"
                    else:
                        is_prohibited = result.get('is_prohibited', False)
                        is_restricted  = result.get('is_restricted', False)
                        is_ste         = result.get('is_ste', False)
                        prohibited_info = result.get('prohibited_info', {})
                        restricted_info = result.get('restricted_info', {})
                        ste_info        = result.get('ste_info', {})
                        chapter_notes   = result.get('chapter_notes', {})
                        itc_policy      = result.get('itc_policy', {})
                        policy_summary  = f"Description: {result.get('description', 'N/A')}\n"

                        # ITC-HS notification data
                        if itc_policy:
                            itc_pol_val = (itc_policy.get('itc_policy') or '').strip()
                            notif_no    = (itc_policy.get('itc_notification') or '').strip()
                            notif_date  = itc_policy.get('itc_date', '')
                            overall     = (itc_policy.get('overall_status') or '').strip()
                            ref_text    = (itc_policy.get('policy_reference_text') or '').strip()
                            if itc_pol_val:
                                policy_summary += f"ITC-HS Policy: {itc_pol_val}\n"
                            if overall:
                                policy_summary += f"Overall Status: {overall}\n"
                            if notif_no:
                                date_str = f" dated {notif_date}" if notif_date else ""
                                policy_summary += f"ITC Notification: {notif_no}{date_str}\n"
                            if ref_text:
                                policy_summary += f"Policy Reference Text: {ref_text}\n"

                    # Core policy decision — based solely on the three restriction tables
                    # Runs for BOTH can_export and get_hs_code_info paths
                    if not is_prohibited and not is_restricted and not is_ste:
                        policy_summary += "Export Policy: FREE — not found in prohibited, restricted, or STE lists."
                    else:
                        if is_prohibited:
                            policy_summary += f"PROHIBITED: {_restriction_detail(prohibited_info)}"
                        if is_restricted:
                            policy_summary += f"\nRESTRICTED: {_restriction_detail(restricted_info)}"
                        if is_ste:
                            entity = ste_info.get('authorized_entity', '')
                            cond   = (ste_info.get('policy_condition') or '').strip()
                            if entity:
                                policy_summary += f"\nSTE: Export only via {entity}"
                                if cond:
                                    policy_summary += f" — {cond}"
                            elif cond:
                                policy_summary += f"\nSTE: {cond}"
                            else:
                                policy_summary += "\nSTE: Canalized through designated State Trading Enterprise"

                    # Chapter notes (if any)
                    if chapter_notes:
                        ch_name = chapter_notes.get('chapter_name', f"Chapter {chapter_notes.get('chapter_code', '?')}")
                        policy_summary += f"\n\nCHAPTER NOTES ({ch_name}):"
                        if chapter_notes.get('main_notes'):
                            policy_summary += f"\nMain Notes: {'; '.join(chapter_notes['main_notes'][:3])}"
                        if chapter_notes.get('export_licensing'):
                            policy_summary += f"\nExport Licensing: {'; '.join(chapter_notes['export_licensing'][:3])}"
                        if chapter_notes.get('policy_conditions'):
                            policy_summary += f"\nPolicy Conditions: {'; '.join(chapter_notes['policy_conditions'][:3])}"
            elif state["policy_results"].get("error"):
                policy_summary = f"Policy agent ran but encountered an error: {state['policy_results']['error']}"
        
        vector_summary = "NOT CHECKED — Vector agent was not invoked for this query."
        if state.get("vector_results"):
            docs = state["vector_results"][:6]
            parts = []
            for d in docs:
                meta = d.get('metadata', {})
                doc_type = d.get('type', 'unknown')

                if doc_type == 'dgft_ftp':
                    chapter = meta.get('chapter', f"Ch-{meta.get('chapter_num', '?')}")
                    section = meta.get('section_full', meta.get('section_id', 'N/A'))
                    label = f"DGFT FTP {chapter} — {section}"
                    # Use full text for policy sections so the LLM doesn't hallucinate
                    excerpt_limit = 1500
                else:
                    label = f"Document: {meta.get('filename', meta.get('agreement', 'N/A'))}"
                    excerpt_limit = 300

                text = d['text']
                excerpt = text if len(text) <= excerpt_limit else text[:excerpt_limit] + "..."
                parts.append(f"{label}\nRelevance: {d['score']:.1%}\nContent:\n{excerpt}")

            vector_summary = "\n\n".join(parts)
        
        # Build HS lookup summary
        hs_lookup_summary = "NOT CHECKED — HS lookup was not invoked for this query."
        if state.get("hs_lookup_results"):
            hs_data = state["hs_lookup_results"]
            if hs_data.get("success") and hs_data.get("results") is not None:
                matches      = hs_data["results"]
                c_type       = hs_data.get("clarification_type")   # "no_match"|"confirm_one"|"pick_one"|"too_broad"|None
                c_msg        = hs_data.get("clarification_message", "")
                needs_cls    = hs_data.get("needs_clarification", False)
                search_term  = hs_data.get("search_term", "")

                if c_type == "no_match":
                    hs_lookup_summary = (
                        f"NO RESULTS — Search for '{search_term}' returned 0 matches.\n"
                        f"CLARIFICATION NEEDED: {c_msg}"
                    )
                elif c_type in ("pick_one", "confirm_one"):
                    lines = [
                        f"CLARIFICATION NEEDED ({c_type.upper()}): {c_msg}",
                        "",
                        "| HS Code | Chapter | Level | Description | Confidence |",
                        "|---------|---------|-------|-------------|------------|",
                    ]
                    level_label = {1: "Heading", 2: "Subheading", 3: "Tariff line"}
                    for m in matches[:8]:
                        lvl   = level_label.get(m.get("code_level", 3), "Code")
                        score = f"{m.get('score', 0):.0%}"
                        desc  = m["description"]  # full description — DB already abbreviates
                        lines.append(f"| {m['hs_code']} | Ch-{m['chapter']} | {lvl} | {desc} | {score} |")
                    hs_lookup_summary = "\n".join(lines)
                elif c_type == "too_broad":
                    lines = [
                        f"TOO MANY RESULTS ({hs_data['count']}) — too broad to list. {c_msg}",
                        "",
                        "Sample matches (top 5):",
                        "| HS Code | Chapter | Description |",
                        "|---------|---------|-------------|",
                    ]
                    for m in matches[:5]:
                        lines.append(f"| {m['hs_code']} | Ch-{m['chapter']} | {m['description']} |")
                    hs_lookup_summary = "\n".join(lines)
                else:
                    # No clarification needed — single good match (or old-format ambiguous)
                    parts = [f"Search term: {search_term}", f"Matches found: {hs_data.get('count', 0)}"]
                    if hs_data.get("is_ambiguous"):
                        parts.append("AMBIGUOUS — Multiple HS codes match. Present ALL options to user.")
                    for m in matches[:20]:
                        ch  = m.get("chapter", "?")
                        lvl = {1: "heading", 2: "subheading", 3: "tariff"}.get(m.get("code_level", 3), "")
                        parts.append(f"  HS {m['hs_code']} (Ch-{ch}{', ' + lvl if lvl else ''}): {m['description']}")
                    hs_lookup_summary = "\n".join(parts)

                # Propagate flag to state so the caller (app.py) can detect it
                state["needs_clarification"] = needs_cls
        
        # Build agreement summary
        agreement_summary = "NOT CHECKED — Agreements agent was not invoked for this query."
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
            "query_type": state.get("query_type", "unknown"),
            "sql_results": sql_summary,
            "policy_results": policy_summary,
            "vector_results": vector_summary,
            "agreement_results": agreement_summary,
            "hs_lookup_results": hs_lookup_summary
        })
        
        state["final_answer"] = final_answer
        state["next_agent"] = None
        
        return state
