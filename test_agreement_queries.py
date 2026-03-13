"""
Test Queries for the Enhanced Export Advisory System
=====================================================

Tests ALL agents in the LangGraph multi-agent system.
Covers:
  1. Direct agreement queries (routes to AgreementsAgent)
  2. Combined queries (SQL + Policy + Agreements)
  3. Policy queries that should also surface restrictions
  4. Cross-reference resolution in agreements
  5. HS master lookup (ambiguous + exact)
  6. Product-name → full pipeline (HS lookup → Combined)
  7. Vector/DGFT FTP search
  8. Multi-turn conversation memory

Usage:
    python test_agreement_queries.py           # Run all test queries
    python test_agreement_queries.py --quick   # Run first 3 only
    python test_agreement_queries.py --interactive  # Interactive mode after tests
"""

import sys
import time
from datetime import datetime

# ========== TEST QUERIES ==========

TEST_QUERIES = [
    # ─────────────────────────────────────────────────────────────
    # GROUP 1: AGREEMENTS AGENT (should route to → agreements)
    # ─────────────────────────────────────────────────────────────
    {
        "query": "What are the rules of origin for exporting textiles to Australia under the India-Australia trade agreement?",
        "expected_route": "agreements",
        "description": "Tests agreement search for rules of origin (Australia ECTA Chapter 4)",
        "should_mention": ["Article 4", "origin", "Australia"],
    },
    {
        "query": "What tariff benefits does the India-UAE CEPA provide for agricultural products?",
        "expected_route": "agreements",
        "description": "Tests agreement search for tariff provisions (UAE CEPA Chapter 2)",
        "should_mention": ["tariff", "UAE", "CEPA"],
    },
    {
        "query": "What are the customs procedures under the India-UK FTA?",
        "expected_route": "agreements",
        "description": "Tests agreement search for customs procedures (UK CETA Chapter 5)",
        "should_mention": ["customs", "UK"],
    },
    {
        "query": "What are the dispute settlement provisions in the India-Australia ECTA?",
        "expected_route": "agreements",
        "description": "Tests agreement search for dispute settlement (Australia ECTA Chapter 13)",
        "should_mention": ["dispute", "settlement", "Australia"],
    },
    {
        "query": "What SPS (sanitary and phytosanitary) measures are in the India-UAE CEPA?",
        "expected_route": "agreements",
        "description": "Tests SPS measures in UAE agreement",
        "should_mention": ["sanitary", "phytosanitary", "UAE"],
    },

    # ─────────────────────────────────────────────────────────────
    # GROUP 2: COMBINED QUERIES (should route to → combined)
    # ─────────────────────────────────────────────────────────────
    {
        "query": "Can I export vegetables (chapter 07) to Australia and what does the trade agreement say about tariff benefits?",
        "expected_route": "combined",
        "description": "Tests combined: SQL data + policy check + agreement search",
        "should_mention": ["chapter 07", "Australia", "tariff"],
    },
    {
        "query": "What are the export values and any trade agreement benefits for textiles to UAE?",
        "expected_route": "combined",
        "description": "Tests combined: export stats + agreement provisions for UAE",
        "should_mention": ["textiles", "UAE"],
    },

    # ─────────────────────────────────────────────────────────────
    # GROUP 3: POLICY QUERIES (should route to → policy)
    # ─────────────────────────────────────────────────────────────
    {
        "query": "Can I export HS 070310 to Australia?",
        "expected_route": "policy",
        "description": "Tests specific HS code policy check (potatoes)",
        "should_mention": ["070310"],
    },
    {
        "query": "Are there any restrictions on exporting rice to UAE?",
        "expected_route": "policy",
        "description": "Tests product-name based policy lookup with restriction check",
        "should_mention": ["rice", "restrict"],
    },

    # ─────────────────────────────────────────────────────────────
    # GROUP 4: SQL QUERIES (should route to → sql)
    # ─────────────────────────────────────────────────────────────
    {
        "query": "What is the total export value for chapter 61 to UK?",
        "expected_route": "sql",
        "description": "Tests SQL aggregation for export statistics",
        "should_mention": ["chapter 61", "UK"],
    },
    {
        "query": "Show me all prohibited items in chapter 07",
        "expected_route": "sql",
        "description": "Tests SQL listing of prohibited items",
        "should_mention": ["prohibited"],
    },

    # ─────────────────────────────────────────────────────────────
    # GROUP 5: MONTHLY DATA QUERIES (should route to → sql)
    # ─────────────────────────────────────────────────────────────
    {
        "query": "What were the monthly exports of HS 610910 to UAE in 2024?",
        "expected_route": "sql",
        "description": "Tests month-by-month export data retrieval from monthly_export_statistics",
        "should_mention": ["610910", "UAE"],
    },
    {
        "query": "Which month had the highest exports for chapter 85 to Australia?",
        "expected_route": "sql",
        "description": "Tests best-month aggregation query on monthly data",
        "should_mention": ["85", "Australia"],
    },
    {
        "query": "Show quarterly export trend for textiles to UK in 2024",
        "expected_route": "sql",
        "description": "Tests quarterly aggregation from monthly_export_statistics",
        "should_mention": ["textile", "UK"],
    },
    {
        "query": "What is the seasonal pattern for vegetable exports to UAE?",
        "expected_route": "sql",
        "description": "Tests seasonal/monthly pattern query for agriculture products",
        "should_mention": ["vegetable", "UAE"],
    },
    {
        "query": "Compare month-over-month growth for HS 850440 exports to all countries",
        "expected_route": "sql",
        "description": "Tests monthly growth percentage query across countries",
        "should_mention": ["850440", "growth"],
    },
    {
        "query": "What were the total YTD exports for chapter 61 to Australia vs UAE in 2024?",
        "expected_route": "sql",
        "description": "Tests year-to-date comparison across countries from monthly data",
        "should_mention": ["61"],
    },

    # ─────────────────────────────────────────────────────────────
    # GROUP 6: CROSS-REFERENCE TESTS
    # ─────────────────────────────────────────────────────────────
    {
        "query": "What does Article 4.3 of the India-Australia agreement say about goods not wholly produced?",
        "expected_route": "agreements",
        "description": "Tests specific article lookup with cross-reference resolution (Art 4.3 refs 4.4, 4.6)",
        "should_mention": ["Article 4.3", "wholly", "origin"],
    },
    {
        "query": "Explain the certificate of origin requirements for UK exports under the trade agreement",
        "expected_route": "agreements",
        "description": "Tests certificate of origin search in UK CETA Annex 3C",
        "should_mention": ["certificate", "origin", "UK"],
    },

    # ─────────────────────────────────────────────────────────────
    # GROUP 7: HS MASTER LOOKUP (should route to → combined/policy)
    # Tests the new hs_master_8_digit table (13,407 codes)
    # ─────────────────────────────────────────────────────────────
    {
        "query": "What is the HS code for roses?",
        "expected_route": "combined",
        "description": "Tests HS master lookup — specific product (should find 6024000 ROSES)",
        "should_mention": ["6024000", "rose"],
    },
    {
        "query": "What is the HS code for honey?",
        "expected_route": "combined",
        "description": "Tests HS master lookup — specific product (should find 4090000 NATURAL HONEY)",
        "should_mention": ["4090000", "honey"],
    },
    {
        "query": "What are the HS codes for plants?",
        "expected_route": "combined",
        "description": "Tests AMBIGUOUS HS lookup — 'plants' matches 10+ codes, should show a table",
        "should_mention": ["plant"],
    },
    {
        "query": "HS code for mushrooms?",
        "expected_route": "combined",
        "description": "Tests HS master lookup — should find MUSHROOM SPAWN etc.",
        "should_mention": ["mushroom"],
    },

    # ─────────────────────────────────────────────────────────────
    # GROUP 8: PRODUCT NAME → FULL PIPELINE (HS lookup + Combined)
    # User gives a product name, system resolves HS code, then
    # runs SQL + Policy + Agreements + DGFT FTP agents
    # ─────────────────────────────────────────────────────────────
    {
        "query": "Can I export roses to Australia? Show trade data and any restrictions.",
        "expected_route": "combined",
        "description": "Tests full pipeline: product name → HS lookup → SQL + Policy + Agreements",
        "should_mention": ["rose", "Australia"],
    },
    {
        "query": "I want to export natural honey to UAE, what are the rules?",
        "expected_route": "combined",
        "description": "Tests product name → HS 4090000 → combined (policy + agreements + SQL)",
        "should_mention": ["honey", "UAE"],
    },
    {
        "query": "Can I export cactus to UK? Any restrictions or tariff benefits?",
        "expected_route": "combined",
        "description": "Tests product name → HS 6022020 CACTUS → Combined flow with UK CETA lookup",
        "should_mention": ["cactus", "UK"],
    },
    {
        "query": "Export potatoes to Australia with all details",
        "expected_route": "combined",
        "description": "Tests product name → HS 7011000 POTATO SEEDS → Combined with Australia ECTA",
        "should_mention": ["potato", "Australia"],
    },

    # ─────────────────────────────────────────────────────────────
    # GROUP 9: VECTOR SEARCH / DGFT FTP (should route to → vector)
    # ─────────────────────────────────────────────────────────────
    {
        "query": "What does DGFT say about export licensing procedures?",
        "expected_route": "vector",
        "description": "Tests DGFT FTP vector search for licensing procedures",
        "should_mention": ["licens", "DGFT"],
    },
    {
        "query": "What are the DGFT foreign trade policy provisions for special economic zones?",
        "expected_route": "vector",
        "description": "Tests DGFT FTP vector search for SEZ provisions",
        "should_mention": ["special economic zone"],
    },

    # ─────────────────────────────────────────────────────────────
    # GROUP 10: MULTI-TURN MEMORY (uses same session_id)
    # These MUST run in order within the same session
    # ─────────────────────────────────────────────────────────────
    {
        "query": "Can I export HS 6031100 to UAE?",
        "expected_route": "combined",
        "description": "Multi-turn STEP 1: Initial query about roses (HS 6031100) to UAE",
        "should_mention": ["6031100"],
        "session_id": "multi_turn_test",
    },
    {
        "query": "What about to Australia instead?",
        "expected_route": "combined",
        "description": "Multi-turn STEP 2: Follow-up changing country — agent should remember HS code",
        "should_mention": ["Australia"],
        "session_id": "multi_turn_test",
    },
]


def run_tests(quick_mode=False, interactive_after=False):
    """Run test queries against the system"""
    
    print("=" * 70)
    print("  EXPORT ADVISORY SYSTEM - AGREEMENT INTEGRATION TESTS")
    print("=" * 70)
    print(f"\n  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Total queries: {len(TEST_QUERIES)}")
    if quick_mode:
        print(f"  Quick mode: running first 3 only")
    print()
    
    # Initialize the system
    print("Initializing multi-agent system...")
    try:
        from agents import ExportAdvisoryGraph
        graph = ExportAdvisoryGraph()
        print("✓ System ready!\n")
    except Exception as e:
        print(f"❌ Failed to initialize: {e}")
        print("\nMake sure you have:")
        print("  1. ANTHROPIC_API_KEY in .env")
        print("  2. Database running (with hs_master_8_digit table)")
        print("  3. agreements_rag_store/ built (run agreements_ingest_enhanced.py)")
        return
    
    # Select queries to run
    queries_to_run = TEST_QUERIES[:3] if quick_mode else TEST_QUERIES
    
    results_log = []
    
    for i, test in enumerate(queries_to_run, 1):
        print(f"\n{'═' * 70}")
        print(f"  TEST {i}/{len(queries_to_run)}: {test['description']}")
        print(f"  Expected Route: {test['expected_route']}")
        print(f"{'═' * 70}")
        print(f"\n  Query: {test['query']}\n")
        
        try:
            start = time.time()
            session_id = test.get("session_id", f"test_{i}")
            result = graph.query(test["query"], session_id=session_id)
            elapsed = time.time() - start
            
            # Check routing
            actual_route = result.get("query_type", "unknown")
            route_match = actual_route == test["expected_route"]
            route_emoji = "✅" if route_match else "⚠️"
            
            print(f"  {route_emoji} Route: {actual_route} (expected: {test['expected_route']})")
            print(f"  ⏱️  Time: {elapsed:.1f}s")
            
            # Check if answer mentions expected terms
            answer_lower = result.get("answer", "").lower()
            mentions_found = []
            mentions_missing = []
            for term in test.get("should_mention", []):
                if term.lower() in answer_lower:
                    mentions_found.append(term)
                else:
                    mentions_missing.append(term)
            
            if mentions_found:
                print(f"  ✅ Mentions: {', '.join(mentions_found)}")
            if mentions_missing:
                print(f"  ⚠️  Missing: {', '.join(mentions_missing)}")
            
            # Show sources
            print(f"\n  Sources ({len(result.get('sources', []))}):")
            for src in result.get("sources", []):
                src_type = src.get("type", "unknown")
                if src_type == "trade_agreements":
                    print(f"    📜 {src_type}: {src.get('num_results', 0)} results from {', '.join(src.get('agreements', []))}")
                    if src.get("cross_refs_included"):
                        print(f"       Cross-refs resolved: {src['cross_refs_included']}")
                elif src_type == "sql":
                    print(f"    🗄️  {src_type}: {src.get('database', 'N/A')}")
                elif src_type == "policy_check":
                    print(f"    📋 {src_type}: HS={src.get('hs_code', 'N/A')}, Country={src.get('country', 'N/A')}")
                elif src_type == "hs_master_lookup":
                    matches = src.get('matches_found', 0)
                    ambig = " (AMBIGUOUS)" if src.get('is_ambiguous') else ""
                    print(f"    🔍 {src_type}: {matches} matches for '{src.get('search_term', '?')}'{ambig}")
                else:
                    print(f"    📎 {src_type}")
            
            # Show answer preview (first 300 chars)
            answer_preview = result.get("answer", "No answer")[:300]
            print(f"\n  Answer Preview:\n  {'-' * 60}")
            for line in answer_preview.split("\n"):
                print(f"  {line}")
            print(f"  {'-' * 60}")
            
            results_log.append({
                "query": test["query"],
                "route_match": route_match,
                "actual_route": actual_route,
                "expected_route": test["expected_route"],
                "mentions_found": mentions_found,
                "mentions_missing": mentions_missing,
                "elapsed": elapsed,
                "success": True,
            })
            
        except Exception as e:
            print(f"\n  ❌ Error: {e}")
            results_log.append({
                "query": test["query"],
                "route_match": False,
                "actual_route": "error",
                "expected_route": test["expected_route"],
                "mentions_found": [],
                "mentions_missing": test.get("should_mention", []),
                "elapsed": 0,
                "success": False,
            })
        
        # Small delay between queries to avoid rate limits
        if i < len(queries_to_run):
            time.sleep(1)
    
    # ========== SUMMARY ==========
    print(f"\n\n{'=' * 70}")
    print("  TEST SUMMARY")
    print(f"{'=' * 70}\n")
    
    total = len(results_log)
    route_correct = sum(1 for r in results_log if r["route_match"])
    successful = sum(1 for r in results_log if r["success"])
    avg_time = sum(r["elapsed"] for r in results_log) / total if total > 0 else 0
    
    print(f"  Total Tests:     {total}")
    print(f"  Successful:      {successful}/{total}")
    print(f"  Routing Correct: {route_correct}/{total}")
    print(f"  Avg Response:    {avg_time:.1f}s")
    
    print(f"\n  {'Query':<60} {'Route':>10} {'Time':>6}")
    print(f"  {'─' * 60} {'─' * 10} {'─' * 6}")
    for r in results_log:
        status = "✅" if r["route_match"] else "⚠️"
        q_short = r["query"][:57] + "..." if len(r["query"]) > 57 else r["query"]
        print(f"  {q_short:<60} {status} {r['actual_route']:>8} {r['elapsed']:>5.1f}s")
    
    print(f"\n{'=' * 70}")
    
    # Interactive mode
    if interactive_after:
        print("\n\nINTERACTIVE MODE - Ask your own questions!")
        print("(Type 'quit' to exit)\n")
        
        while True:
            user_input = input("\nYour query: ").strip()
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("\nGoodbye!")
                break
            if not user_input:
                continue
            
            try:
                result = graph.query(user_input)
                print(f"\n{graph.format_response(result)}")
            except Exception as e:
                print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    interactive = "--interactive" in sys.argv
    run_tests(quick_mode=quick, interactive_after=interactive)
