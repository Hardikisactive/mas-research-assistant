"""
Base agent class shared by all MAS agents.
Provides LLM access, security guardrails, observability hooks, and a standard run() interface.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app.config.settings import get_settings
from app.security.guardrails import validate_retrieved_content

logger = logging.getLogger(__name__)


def _get_llm(model: Optional[str] = None):
    """Instantiate a LangChain LLM from settings. Returns None if no API key configured."""
    settings = get_settings()
    api_key = settings.openai_api_key
    if not api_key:
        logger.warning("OPENAI_API_KEY not set — LLM will return stub responses")
        return None
    try:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model or settings.openai_model,
            api_key=api_key,
            base_url=settings.openai_base_url,
            temperature=0.2,
        )
    except Exception as e:
        logger.error(f"Failed to initialise LLM: {e}")
        return None


class BaseAgent:
    """
    Abstract base for all research agents.
    Subclasses must implement _execute(state) -> dict.
    """

    name: str = "base"
    role: str = "base"

    def __init__(self):
        self._llm = None
        self.settings = get_settings()

    def get_llm(self):
        if self._llm is None:
            self._llm = _get_llm()
        return self._llm

    def llm_invoke(self, prompt: str, system: str = "") -> str:
        """Call LLM and return text response. Falls back to a stub if LLM unavailable."""
        llm = self.get_llm()
        if llm is None:
            return f"[{self.name}] LLM not available. Stub response for: {prompt[:80]}"
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            messages = []
            if system:
                messages.append(SystemMessage(content=system))
            messages.append(HumanMessage(content=prompt))
            response = llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"LLM invocation failed in {self.name}: {e}")
            return f"[{self.name}] Error calling LLM: {e}"

    def safe_content(self, text: str, source: str = "unknown") -> str:
        """Run retrieved content through guardrails before using it."""
        sanitized, has_injection = validate_retrieved_content(text, source=source)
        if has_injection:
            logger.warning(f"[{self.name}] Injection pattern in content from {source}")
        return sanitized

    def run(self, state: dict) -> dict:
        """Entry point called by LangGraph. Wraps _execute with timing and error handling."""
        start = time.perf_counter()
        trace_entry = {"agent": self.name, "start_time": start}
        try:
            result = self._execute(state)
            duration_ms = (time.perf_counter() - start) * 1000
            trace_entry.update({"duration_ms": round(duration_ms, 2), "status": "ok"})
            logger.info(f"[{self.name}] completed in {duration_ms:.0f}ms")
        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            trace_entry.update({"duration_ms": round(duration_ms, 2), "status": "error", "error": str(exc)})
            logger.error(f"[{self.name}] error: {exc}")
            result = {**state, "error": str(exc), "agent_errors": state.get("agent_errors", []) + [f"{self.name}: {exc}"]}

        # Append to agent trace
        trace = list(state.get("agent_trace", []))
        trace.append(trace_entry)
        result["agent_trace"] = trace
        return result

    def _execute(self, state: dict) -> dict:
        raise NotImplementedError(f"{self.name}._execute() must be implemented")
