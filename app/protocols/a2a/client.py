"""
A2A Client — CrewAI side sends tasks to the ADK agent.

This module provides the A2AClient used by CrewAI agents to communicate
with the ADK RAG Agent via the A2A protocol (HTTP/JSON).

Also provides a synchronous CrewAI tool wrapper (A2ARagTool) that
the Research/Supervisor agents can use directly.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

import httpx
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

from app.schemas.messages import A2ATaskRequest, A2ATaskResponse
from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class A2AClient:
    """
    HTTP client for the A2A protocol.
    Sends tasks to the ADK agent endpoint and handles responses.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.adk_agent_url).rstrip("/")
        self._timeout = timeout or settings.a2a_timeout_seconds

    def send_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        requesting_agent: str = "crewai",
    ) -> A2ATaskResponse:
        """
        Send a task to the ADK agent and return the response.

        Args:
            task_type: Task type string (e.g., "rag_query").
            payload: Task payload dict.
            requesting_agent: Name of the sending agent (for audit).

        Returns:
            A2ATaskResponse with result or error.
        """
        task_id = str(uuid.uuid4())
        request = A2ATaskRequest(
            task_id=task_id,
            requesting_agent=requesting_agent,
            task_type=task_type,
            payload=payload,
            timeout_seconds=self._timeout,
        )

        start = time.perf_counter()
        logger.info(
            f"A2A send: id={task_id} type={task_type} "
            f"to={self._base_url}/a2a/task"
        )

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/a2a/task",
                    json=request.model_dump(mode="json"),
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()

            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                f"A2A response: id={task_id} status={data.get('status')} "
                f"in {duration_ms:.0f}ms"
            )

            return A2ATaskResponse(
                task_id=data.get("task_id", task_id),
                responding_agent=data.get("responding_agent", "adk-agent"),
                status=data.get("status", "error"),
                result=data.get("result"),
                error_message=data.get("error_message"),
                duration_ms=data.get("duration_ms", duration_ms),
            )

        except httpx.TimeoutException:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(f"A2A timeout after {duration_ms:.0f}ms: {task_id}")
            return A2ATaskResponse(
                task_id=task_id,
                responding_agent="unknown",
                status="timeout",
                error_message=f"A2A request timed out after {self._timeout}s",
                duration_ms=duration_ms,
            )

        except httpx.ConnectError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(f"A2A connection failed: {exc}")
            return A2ATaskResponse(
                task_id=task_id,
                responding_agent="unknown",
                status="error",
                error_message=f"Cannot connect to ADK agent at {self._base_url}: {exc}",
                duration_ms=duration_ms,
            )

        except Exception as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(f"A2A error: {exc}", exc_info=True)
            return A2ATaskResponse(
                task_id=task_id,
                responding_agent="unknown",
                status="error",
                error_message=str(exc)[:500],
                duration_ms=duration_ms,
            )

    def check_health(self) -> dict:
        """Check if the ADK agent server is reachable."""
        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(f"{self._base_url}/health")
                response.raise_for_status()
                return {"reachable": True, **response.json()}
        except Exception as exc:
            return {"reachable": False, "error": str(exc)[:200]}

    def get_agent_card(self) -> dict:
        """Fetch the ADK agent's capability card."""
        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(f"{self._base_url}/.well-known/agent.json")
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            return {"error": str(exc)[:200]}


# ─── CrewAI Tool Wrapper ─────────────────────────────────────────────────────

class A2ARagQueryInput(BaseModel):
    query: str = Field(description="Question to answer from indexed documents")
    top_k: int = Field(default=5, ge=1, le=20, description="Number of chunks to retrieve")


class A2ARagTool(BaseTool):
    """
    CrewAI tool that sends a RAG query to the ADK agent via A2A protocol.
    Provides cross-framework interoperability: CrewAI ↔ A2A ↔ ADK.
    """
    name: str = "a2a_rag_query"
    description: str = (
        "Query indexed documents via the ADK RAG Agent. "
        "Use this when the question relates to uploaded PDF/TXT/DOCX files. "
        "Input: question string. Returns: answer with document citations."
    )
    args_schema: type[BaseModel] = A2ARagQueryInput

    def _run(self, query: str, top_k: int = 5) -> str:
        """Send RAG query to ADK agent via A2A and return the result."""
        client = A2AClient()

        # Check if server is available
        health = client.check_health()
        if not health.get("reachable"):
            # Fall back to direct local execution if A2A server is not running
            logger.warning(
                "A2A server not reachable — falling back to local RAG execution"
            )
            return self._local_fallback(query, top_k)

        response = client.send_task(
            task_type="rag_query",
            payload={"query": query, "top_k": top_k},
            requesting_agent="crewai_research_agent",
        )

        if response.status == "success" and response.result:
            return json.dumps({
                "source": "ADK RAG Agent (via A2A)",
                "a2a_task_id": response.task_id,
                "answer": response.result.get("answer", ""),
                "success": True,
                "duration_ms": response.duration_ms,
            })
        else:
            return json.dumps({
                "error": response.error_message or "A2A RAG query failed",
                "source": "ADK RAG Agent (via A2A)",
                "success": False,
                "status": response.status,
            })

    def _local_fallback(self, query: str, top_k: int) -> str:
        """Direct local execution when A2A server is not running."""
        try:
            from app.agents.rag.adk_agent import run_adk_rag_agent_sync
            from app.storage.vector_store import VectorStore
            from app.config.settings import get_settings

            settings = get_settings()
            vs = VectorStore(
                store_dir=settings.vector_store_dir,
                embedding_model=settings.embedding_model,
            )
            result = run_adk_rag_agent_sync(query=query, vector_store=vs)
            return json.dumps({
                "source": "ADK RAG Agent (local fallback — A2A server offline)",
                "answer": result.get("answer", ""),
                "success": result.get("success", False),
                "is_fallback": True,
            })
        except Exception as exc:
            logger.error(f"A2A local fallback failed: {exc}")
            return json.dumps({
                "error": f"RAG not available: {exc}",
                "success": False,
            })

