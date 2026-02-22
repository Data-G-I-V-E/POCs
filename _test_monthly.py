"""Test monthly trade data queries through the LangGraph system"""
import sys
import time

from langgraph_export_agent import ExportAdvisoryGraph


def test_query(graph, query, session="test_monthly"):
    print(f"\n{'='*70}")
    print(f"QUERY: {query}")
    print(f"{'='*70}")
    
    start = time.time()
    result = graph.query(query, session_id=session)
    elapsed = time.time() - start
    
    print(f"\nRoute: {result.get('query_type', 'N/A')}")
    print(f"Time: {elapsed:.1f}s")
    print(f"\nAnswer (first 600 chars):")
    answer = result.get('answer', 'No answer')
    print(answer[:600])
    if len(answer) > 600:
        print(f"  ... ({len(answer)} total chars)")
    
    sources = result.get('sources', [])
    print(f"\nSources: {len(sources)}")
    for s in sources[:3]:
        print(f"  - {s.get('type', 'unknown')}")
    
    return result


def main():
    print("Initializing LangGraph system...")
    graph = ExportAdvisoryGraph()
    print("Ready!\n")
    
    queries = [
        # 1. Direct monthly query - should route to SQL
        "What were the monthly exports of HS 610910 to UAE in 2024?",
        # 2. Chapter-level monthly - should use v_monthly_exports with chapter = '85'
        "Which month had the highest exports for chapter 85 to Australia?",
        # 3. Quarterly trend - should use v_quarterly_exports
        "Show quarterly export trend for textiles to UK in 2024",
    ]
    
    # Support running a single query by index
    if len(sys.argv) > 1:
        idx = int(sys.argv[1])
        queries = [queries[idx]]
    
    for q in queries:
        test_query(graph, q)
    
    print(f"\n{'='*70}")
    print("ALL TESTS COMPLETE")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
