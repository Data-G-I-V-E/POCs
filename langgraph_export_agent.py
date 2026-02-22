"""
LangGraph Multi-Agent Export Advisory System

Backward compatibility shim — all logic now lives in the agents/ package.
Import from here or directly from agents/:

    from langgraph_export_agent import ExportAdvisoryGraph
    # or
    from agents import ExportAdvisoryGraph
"""

from agents import (
    AgentState,
    QueryRouter,
    SQLAgent,
    PolicyAgent,
    VectorAgent,
    AgreementsAgent,
    AnswerSynthesizer,
    ExportAdvisoryGraph,
    interactive_demo,
)

__all__ = [
    "AgentState",
    "QueryRouter",
    "SQLAgent",
    "PolicyAgent",
    "VectorAgent",
    "AgreementsAgent",
    "AnswerSynthesizer",
    "ExportAdvisoryGraph",
    "interactive_demo",
]

if __name__ == "__main__":
    interactive_demo()
