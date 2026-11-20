"""
A2A Server — ADK agent exposed as an A2A-compatible HTTP endpoint.

This FastAPI server makes the ADK RAG Agent callable via the A2A protocol.
The CrewAI side sends JSON task requests; this server dispatches to the ADK
agent and returns structured JSON responses.

Endpoint: POST /a2a/task
Agent Card: GET /.well-known/agent.json
Health:     GET /health

Run standalone:
    python -m app.protocols.a2a.server
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.schemas.messages import A2ATaskRequest, A2ATaskResponse, AgentCard
from app.config.settings import get_settings
from app.agents.rag.adk_agent import run_adk_rag_agent
from app.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)

# ─── Agent Card (A2A Discovery) ──────────────────────────────────────────────

def _get_agent_card(settings) -> dict:
    """Return the ADK RAG Agent's capability card."""
    return {
        "agent_id": "adk-rag-agent-001",
        "name": "ADK RAG Agent",
        "framework": "google-adk",
        "version": "1.0",
        "description": (
            "Document retrieval agent using Google ADK + FAISS. "
            "Answers questions about indexed documents via RAG."
        ),
        "capabilities": [
            "document_retrieval",
            "rag_qa",
            "citation_generation",
        ],
        "endpoint": f"{settings.adk_agent_url}/a2a/task",
        "input_modes": ["text"],
        "output_modes": ["text", "json"],
        "authentication": {"schemes": []},
    }


# ─── Global state ─────────────────────────────────────────────────────────────

_vector_store: Optional[VectorStore] = None


def get_vs() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        settings = get_settings()
        _vector_store = VectorStore(
            store_dir=settings.vector_store_dir,
            embedding_model=settings.embedding_model,
        )
    return _vector_store


# ─── FastAPI App ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize on startup."""
    logger.info("A2A Server starting — initializing vector store")
    get_vs()  # Warm up
    yield
    logger.info("A2A Server shutting down")


app = FastAPI(
    title="ADK RAG Agent — A2A Endpoint",
    description="Google ADK RAG agent exposed via A2A protocol",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check endpoint for load balancers / Cloud Run."""
    vs = get_vs()
    return {
        "status": "healthy",
        "agent": "adk-rag-agent",
        "framework": "google-adk",
        "documents_indexed": vs.total_chunks,
        "vector_store_available": vs.is_available,
    }


@app.get("/.well-known/agent.json")
async def agent_card():
    """A2A agent discovery endpoint."""
    settings = get_settings()
    return JSONResponse(_get_agent_card(settings))


class A2ATaskBody(BaseModel):
    """HTTP request body for A2A task submission."""
    task_id: Optional[str] = None
    requesting_agent: str = "crewai_supervisor"
    task_type: str = "rag_query"
    payload: dict[str, Any] = {}
    timeout_seconds: int = 60


@app.post("/a2a/task")
async def handle_task(body: A2ATaskBody, request: Request) -> dict:
    """
    Receive an A2A task from CrewAI, run the ADK agent, return the result.
    
    Supported task types:
    - rag_query: Answer a question using document retrieval
    - health_check: Return agent status
    """
    task_id = body.task_id or str(uuid.uuid4())
    start = time.perf_counter()

    logger.info(
        f"A2A task received: id={task_id} type={body.task_type} "
        f"from={body.requesting_agent}"
    )

    try:
        if body.task_type == "health_check":
            duration_ms = (time.perf_counter() - start) * 1000
            return A2ATaskResponse(
                task_id=task_id,
                responding_agent="adk-rag-agent",
                status="success",
                result={"agent_status": "healthy", "documents_indexed": get_vs().total_chunks},
                duration_ms=duration_ms,
            ).model_dump(mode="json")

        elif body.task_type == "rag_query":
            query = body.payload.get("query", "")
            top_k = int(body.payload.get("top_k", 5))
            session_id = body.payload.get("session_id")

            if not query:
                raise HTTPException(status_code=400, detail="payload.query is required")

            # Run ADK RAG agent
            result = await run_adk_rag_agent(
                query=query,
                vector_store=get_vs(),
                session_id=session_id,
            )

            duration_ms = (time.perf_counter() - start) * 1000
            return A2ATaskResponse(
                task_id=task_id,
                responding_agent="adk-rag-agent",
                status="success" if result.get("success") else "error",
                result=result,
                error_message=result.get("error") if not result.get("success") else None,
                duration_ms=duration_ms,
            ).model_dump(mode="json")

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown task_type: {body.task_type}. "
                       "Supported: rag_query, health_check",
            )

    except HTTPException:
        raise
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.error(f"A2A task error: {exc}", exc_info=True)
        return A2ATaskResponse(
            task_id=task_id,
            responding_agent="adk-rag-agent",
            status="error",
            error_message=str(exc)[:500],
            duration_ms=duration_ms,
        ).model_dump(mode="json")


if __name__ == "__main__":
    from app.config.settings import get_settings
    from app.observability.logger import setup_logging
    settings = get_settings()
    setup_logging(settings.log_level)
    uvicorn.run(
        app,
        host=settings.adk_agent_host,
        port=settings.adk_agent_port,
        log_level=settings.log_level.lower(),
    )

