"""
CrewAI Research Agent — web search using DuckDuckGo (or SerpAPI).
Uses a ReAct-style tool-use loop to gather external evidence.

Framework: CrewAI
MCP Tool: web_search
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from crewai import Agent, LLM
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from app.config.settings import get_settings
from app.security.guardrails import validate_retrieved_content

logger = logging.getLogger(__name__)


# ─── Web Search Tool (CrewAI Tool) ──────────────────────────────────────────

class WebSearchInput(BaseModel):
    query: str = Field(description="Search query (1-300 characters)")
    max_results: int = Field(default=5, ge=1, le=10, description="Max results to return")


class WebSearchTool(BaseTool):
    """
    DuckDuckGo web search tool exposed to the Research Agent.
    Falls back to mock results if search is unavailable.
    """
    name: str = "web_search"
    description: str = (
        "Search the web for current information. "
        "Input: search query string. "
        "Returns: list of title, URL, snippet results."
    )
    args_schema: type[BaseModel] = WebSearchInput

    def _run(self, query: str, max_results: int = 5) -> str:
        """Execute web search and return JSON results."""
        # Validate input
        query = query.strip()[:300]
        if not query:
            return json.dumps({"error": "Empty query", "results": []})

        settings = get_settings()
        start = time.perf_counter()

        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        try:
            with DDGS() as ddgs:
                raw = list(ddgs.text(query, max_results=max_results))

            results = []
            for r in raw:
                url = r.get("href", "")
                snippet = r.get("body", "")
                # Validate content through guardrails
                snippet, _ = validate_retrieved_content(snippet, source=f"ddg:{url}")
                results.append({
                    "title": r.get("title", ""),
                    "url": url,
                    "snippet": snippet[:500],
                    "source": "duckduckgo",
                })

            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(f"WebSearch: '{query[:50]}' → {len(results)} results in {duration_ms:.0f}ms")
            return json.dumps({
                "results": results,
                "query": query,
                "result_count": len(results),
                "duration_ms": round(duration_ms, 1),
                "tool_available": True,
            })

        except ImportError:
            logger.warning("duckduckgo-search not installed")
            return json.dumps({
                "error": "Web search not available (duckduckgo-search not installed)",
                "results": [],
                "tool_available": False,
            })
        except Exception as exc:
            logger.error(f"Web search failed: {exc}")
            return json.dumps({
                "error": str(exc)[:200],
                "results": [],
                "tool_available": False,
            })


def build_research_agent(llm=None) -> Agent:
    """Create and return the CrewAI Research Agent."""
    settings = get_settings()
    if llm is None:
        llm = settings.get_crewai_llm()

    return Agent(
        role="Web Research Specialist",
        goal=(
            "Search the web for accurate, current information relevant to the query. "
            "Collect source URLs, titles, and evidence excerpts. "
            "Distinguish verified facts from uncertain claims."
        ),
        backstory=(
            "You are a skilled web researcher with deep expertise in finding reliable sources. "
            "You use DuckDuckGo to search for information and critically evaluate sources. "
            "You never fabricate URLs or citations. When evidence is weak or missing, you say so. "
            "You record your reasoning: what you searched for, what you found, and why it's relevant."
        ),
        tools=[WebSearchTool()],
        verbose=True,
        allow_delegation=False,
        llm=llm,
        max_iter=5,
        memory=False,
    )
