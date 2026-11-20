"""
LangGraph TypedDict state shared across all agents in the pipeline.
"""
from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    """
    Shared state passed through LangGraph nodes.
    All fields are optional so nodes can update only what they produce.
    """
    # Core query info
    query: str
    session_id: str

    # Conversation messages (LangGraph messages list)
    messages: list[Any]

    # Agent outputs
    web_results: list[dict]       # from research agent
    doc_results: list[dict]       # from RAG agent
    calculations: list[dict]      # from data analysis agent
    synthesis: str                # from synthesis agent
    critique: str                 # from critic agent
    final_answer: str             # assembled by supervisor

    # Sources collected across agents
    sources: list[dict]

    # Routing / control
    current_agent: str
    next_agent: str
    iteration: int
    max_iterations: int
    should_revise: bool           # critic requests revision

    # Error handling
    error: Optional[str]
    agent_errors: list[str]

    # Metadata
    metadata: dict[str, Any]
    agent_trace: list[dict]       # timing and decision log
    confidence: float
