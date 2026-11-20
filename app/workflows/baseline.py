"""
Baseline workflow — single LLM call with no multi-agent orchestration.
Used as the comparison baseline for evaluation (H1 hypothesis testing).
"""
from __future__ import annotations
import logging, time
from app.state.blackboard import get_blackboard
from app.config.settings import get_settings
from app.schemas.outputs import FinalResponse
from app.schemas.base import VerificationStatus, WorkflowPattern, ExecutionSummary

logger = logging.getLogger(__name__)


def run_baseline(
    query: str,
    sanitized_query: str,
    run_id: str,
    persona: str = "RESEARCHER",
) -> FinalResponse:
    """Single LLM baseline — no tools, no multi-agent, no RAG."""
    bb = get_blackboard()
    settings = get_settings()
    start = time.perf_counter()
    is_mock = not settings.has_llm_configured()

    bb.update_field(run_id, "current_status", "RUNNING", "baseline")
    bb.record_event(run_id, "baseline", "started", "RUNNING", sanitized_query[:80])

    try:
        if not is_mock:
            import google.genai as genai
            client = genai.Client(api_key=settings.google_api_key)
            prompt = (
                f"You are a knowledgeable research assistant. "
                f"Answer this question as accurately as possible without using any tools "
                f"or external sources (respond from your training knowledge only):\n\n"
                f"Question: {sanitized_query}\n\nProvide a thorough, accurate answer."
            )
            resp = client.models.generate_content(
                model=settings.adk_model, contents=prompt
            )
            answer = resp.text if hasattr(resp, "text") else str(resp)
        else:
            answer = (
                f"[Mock Baseline] Single-LLM answer for: {sanitized_query}\n"
                "No API key configured. This is a stub."
            )

        total_ms = (time.perf_counter() - start) * 1000
        bb.update_field(run_id, "current_status", "COMPLETED", "baseline")
        bb.record_event(run_id, "baseline", "completed", "SUCCESS",
                        f"Done in {total_ms:.0f}ms", duration_ms=total_ms)

        return FinalResponse(
            run_id=run_id,
            query=query,
            sanitized_query=sanitized_query,
            answer=answer,
            verification_status=VerificationStatus.PENDING,
            limitations=[
                "No retrieval — answer based on training data only",
                "No fact-checking against current sources",
                "Single LLM baseline (no multi-agent)",
            ],
            agents_used=["baseline_llm"],
            workflow_pattern=WorkflowPattern.BASELINE,
            execution_summary=ExecutionSummary(
                total_duration_ms=total_ms, agent_count=1,
            ),
            is_mock=is_mock,
        )
    except Exception as exc:
        total_ms = (time.perf_counter() - start) * 1000
        logger.error(f"Baseline error: {exc}")
        bb.update_field(run_id, "current_status", "FAILED", "baseline")
        return FinalResponse(
            run_id=run_id, query=query, sanitized_query=sanitized_query,
            answer=f"Baseline failed: {exc}",
            verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            agents_used=["baseline_llm"],
            workflow_pattern=WorkflowPattern.BASELINE,
            execution_summary=ExecutionSummary(total_duration_ms=total_ms),
            is_mock=is_mock,
        )

