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
                sql_summary = str(state["sql_results"]["result"])
            elif state["sql_results"].get("error"):
                sql_summary = f"Query failed: {state['sql_results']['error']}"
        
        policy_summary = "NOT CHECKED — Policy agent was not invoked for this query."
        if state.get("policy_results"):
            if state["policy_results"].get("success"):
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
                            ste_entity = s_info.get('authorized_entity')
                            ste_condition = s_info.get('policy_condition', '')
                            if ste_entity:
                                policy_summary += f"\nSTE REQUIRED: Export only via {ste_entity}"
                            elif ste_condition:
                                policy_summary += f"\nSTE REQUIRED: {ste_condition}"
                            else:
                                policy_summary += "\nSTE REQUIRED: Canalized through designated State Trading Enterprise"
                        # Include chapter notes if available
                        ch_notes = hs_info.get('chapter_notes', {})
                        if ch_notes:
                            ch_name = ch_notes.get('chapter_name', f"Chapter {ch_notes.get('chapter_code', '?')}")
                            policy_summary += f"\n\nCHAPTER NOTES ({ch_name}):"
                            if ch_notes.get('main_notes'):
                                policy_summary += f"\nMain Notes: {'; '.join(ch_notes['main_notes'][:3])}"
                            if ch_notes.get('export_licensing'):
                                policy_summary += f"\nExport Licensing: {'; '.join(ch_notes['export_licensing'][:3])}"
                            if ch_notes.get('policy_conditions'):
                                policy_summary += f"\nPolicy Conditions: {'; '.join(ch_notes['policy_conditions'][:3])}"
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
                            ste_entity = s_info.get('authorized_entity')
                            ste_condition = s_info.get('policy_condition', '')
                            if ste_entity:
                                policy_summary += f"\nSTE DETAILS: Export only via {ste_entity}"
                            elif ste_condition:
                                policy_summary += f"\nSTE DETAILS: {ste_condition}"
                            else:
                                policy_summary += "\nSTE DETAILS: Canalized through designated State Trading Enterprise"
                        # Include chapter notes if available
                        ch_notes = result.get('chapter_notes', {})
                        if ch_notes:
                            ch_name = ch_notes.get('chapter_name', f"Chapter {ch_notes.get('chapter_code', '?')}")
                            policy_summary += f"\n\nCHAPTER NOTES ({ch_name}):"
                            if ch_notes.get('main_notes'):
                                policy_summary += f"\nMain Notes: {'; '.join(ch_notes['main_notes'][:3])}"
                            if ch_notes.get('export_licensing'):
                                policy_summary += f"\nExport Licensing: {'; '.join(ch_notes['export_licensing'][:3])}"
                            if ch_notes.get('policy_conditions'):
                                policy_summary += f"\nPolicy Conditions: {'; '.join(ch_notes['policy_conditions'][:3])}"
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
                        desc  = m["description"][:70]
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
                        lines.append(f"| {m['hs_code']} | Ch-{m['chapter']} | {m['description'][:60]} |")
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
