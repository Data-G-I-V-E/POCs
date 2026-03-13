"""
Agent State Definition

Shared TypedDict that flows through all agents in the LangGraph pipeline.
"""

from typing import TypedDict, Annotated, Sequence, List, Dict, Any, Optional
import operator
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    """State passed between agents"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    user_query: str
    query_type: str  # 'sql', 'vector', 'policy', 'general', 'agreements', 'combined', 'hs_lookup'
    hs_code: Optional[str]
    country: Optional[str]
    product_name: Optional[str]  # Extracted product name from LLM router
    sql_results: Optional[Dict]
    vector_results: Optional[List[Dict]]
    policy_results: Optional[Dict]
    agreement_results: Optional[List[Dict]]  # Trade agreement search results
    hs_lookup_results: Optional[Dict]  # HS master lookup results (includes needs_clarification)
    needs_clarification: Optional[bool]  # True when HS lookup is ambiguous / no match
    final_answer: Optional[str]
    sources: List[Dict[str, Any]]
    next_agent: Optional[str]
