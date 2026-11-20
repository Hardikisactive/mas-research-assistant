"""
CrewAI Supervisor / Orchestrator Agent.

Responsibilities:
- Parse and classify the user query.
- Select appropriate agents and workflow pattern.
- Create a task plan and dispatch to workers.
- Coordinate Blackboard updates.
- Handle retries and failures.
- Produce the final coordinated response.

Framework: CrewAI
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from crewai import Agent, Crew, Task, Process, LLM

from app.config.settings import get_settings
from app.state.blackboard import get_blackboard
from app.observability.metrics import get_metrics

logger = logging.getLogger(__name__)


def build_supervisor_agent(llm=None) -> Agent:
    """
    Create and return the CrewAI Supervisor agent.
    The supervisor orchestrates all specialist agents.
    """
    settings = get_settings()
    if llm is None:
        llm = settings.get_crewai_llm()

    return Agent(
        role="Research Supervisor and Orchestrator",
        goal=(
            "Coordinate specialist agents to answer the user's research query thoroughly "
            "and accurately. Classify the task, select the right agents, dispatch subtasks, "
            "verify results, and synthesise a final answer."
        ),
        backstory=(
            "You are the lead AI research coordinator. You work with a team of specialists: "
            "a Research Agent (web search), a RAG Agent (document retrieval), a Data Analysis "
            "Agent (CSV/tabular data), a Critic Agent (fact-checking), and a Synthesis Agent "
            "(final answer). You never fabricate results — if evidence is insufficient, you "
            "say so clearly. You always cite sources when available."
        ),
        verbose=True,
        allow_delegation=False,  # Supervisor creates Tasks; workers don't re-delegate
        llm=llm,
        max_iter=5,
        memory=False,  # State managed via Blackboard, not agent memory
    )


def classify_query(query: str, llm=None) -> dict:
    """
    Classify the query to determine which agents are needed.
    Returns a dict: {task_type, agents_needed, workflow_pattern, reasoning}
    """
    settings = get_settings()
    
    # Heuristic classification (fast, no LLM call)
    q_lower = query.lower()
    
    needs_research = any(kw in q_lower for kw in [
        "latest", "recent", "current", "news", "what is", "who is", "where",
        "when", "how does", "explain", "compare", "why", "search", "find"
    ])
    needs_rag = any(kw in q_lower for kw in [
        "document", "paper", "pdf", "uploaded", "file", "according to",
        "from the", "in the document", "based on"
    ])
    needs_data = any(kw in q_lower for kw in [
        "csv", "data", "statistics", "average", "median", "count", "chart",
        "plot", "analyse", "analyze", "calculate", "compute", "dataset",
        "spreadsheet", "correlation", "regression"
    ])
    
    agents_needed = ["synthesis"]  # Always include synthesis
    
    if needs_research:
        agents_needed.insert(0, "research")
    if needs_rag:
        agents_needed.insert(0, "rag")
    if needs_data:
        agents_needed.insert(0, "data_analysis")
    
    # Default to research if nothing specific detected
    if len(agents_needed) == 1:
        agents_needed.insert(0, "research")
    
    # Always add critic for quality checking
    agents_needed.append("critic")
    
    # Pattern selection
    if needs_research and needs_rag:
        pattern = "PARALLEL"  # Research and RAG can run concurrently
    elif needs_data and not needs_research and not needs_rag:
        pattern = "SEQUENTIAL"  # Data analysis is sequential
    else:
        pattern = "HIERARCHICAL"  # Default hierarchical
    
    return {
        "task_type": (
            "DATA_ANALYSIS" if needs_data and not needs_research
            else "DOCUMENT_QA" if needs_rag
            else "RESEARCH"
        ),
        "agents_needed": agents_needed,
        "workflow_pattern": pattern,
        "reasoning": (
            f"Research needed: {needs_research}, "
            f"RAG needed: {needs_rag}, "
            f"Data analysis needed: {needs_data}"
        ),
    }
