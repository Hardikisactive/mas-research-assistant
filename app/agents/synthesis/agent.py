"""
CrewAI Synthesis Agent.
Combines verified research, RAG, and data analysis results into a
Pydantic-validated FinalResponse.

Framework: CrewAI
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from crewai import Agent, LLM

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

SYNTHESIS_INSTRUCTIONS = """
You are a research synthesis specialist. Your job is to integrate findings from multiple
specialized agents into a coherent, accurate, well-structured final answer.

Guidelines:
1. Synthesize ALL available evidence (web search, document retrieval, data analysis).
2. Structure your answer clearly: start with the direct answer, then supporting details.
3. Cite sources explicitly: mention document names, URLs, or data files where applicable.
4. State limitations and missing evidence honestly.
5. Do NOT convert conflicting evidence into a definite conclusion — acknowledge the conflict.
6. Do NOT fabricate information not present in the provided evidence.
7. If verification raised issues, address them in your answer.
8. Keep the answer focused and readable (200-500 words unless topic demands more).
9. Format: Use bullet points and headers where they improve readability.
"""


def build_synthesis_agent(llm=None) -> Agent:
    """Create and return the CrewAI Synthesis Agent."""
    settings = get_settings()
    if llm is None:
        llm = settings.get_crewai_llm()

    return Agent(
        role="Research Synthesis Specialist",
        goal=(
            "Combine research findings, document evidence, and data insights into a "
            "comprehensive, well-cited, accurate final answer. "
            "Never fabricate information or hide uncertainty."
        ),
        backstory=(
            "You are an expert scientific writer and research synthesizer. "
            "You read evidence from multiple sources and weave them into clear, "
            "accurate answers. You cite sources faithfully and acknowledge gaps. "
            "You understand that a well-qualified uncertain answer is better than "
            "a confident wrong one."
        ),
        tools=[],  # Synthesis reasons over provided context
        verbose=True,
        allow_delegation=False,
        llm=llm,
        max_iter=3,
        memory=False,
    )

