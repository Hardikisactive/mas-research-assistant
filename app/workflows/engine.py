"""
Main workflow engine — entry point for all workflow patterns.
Routes to hierarchical, parallel, sequential, or baseline.
Applies guardrails, creates Blackboard run, calls the right workflow.
"""
from __future__ import annotations
import logging, time
from typing import Optional
from app.security.guardrails import validate_query, GuardrailViolation
from app.state.blackboard import get_blackboard
from app.observability.metrics import get_metrics
from app.config.settings import get_settings
from app.schemas.outputs import FinalResponse
from app.schemas.base import VerificationStatus, WorkflowPattern, ExecutionSummary

logger = logging.getLogger(__name__)


def run_workflow(
    query: str,
    pattern: str = "HIERARCHICAL",
    persona: str = "RESEARCHER",
    conversation_id: Optional[str] = None,
) -> FinalResponse:
    """
    Main entry point. Validates input, creates a run, dispatches to workflow.

    Args:
        query: Raw user query.
        pattern: Workflow pattern — HIERARCHICAL, PARALLEL, SEQUENTIAL, BASELINE.
        persona: User persona for evaluation tracking.
        conversation_id: Optional grouping ID.

    Returns:
        FinalResponse (always returned, even on error — never raises).
    """
    bb = get_blackboard()
    metrics = get_metrics()
    settings = get_settings()

    # ── Input Guardrails ──────────────────────────────────────────────
    try:
        sanitized_query, warnings = validate_query(
            query, max_length=settings.max_query_length
        )
    except GuardrailViolation as e:
        logger.warning(f"Input rejected: {e.violation_type} — {e}")
        run_id = bb.create_run(query[:100], persona, pattern, conversation_id)
        bb.update_field(run_id, "current_status", "REJECTED", "guardrails")
        return FinalResponse(
            run_id=run_id,
            query=query[:500],
            sanitized_query="",
            answer=(
                f"Your request could not be processed: {str(e)}\n\n"
                "If this is an error, please rephrase your question."
            ),
            verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            limitations=[f"Input rejected: {e.violation_type}"],
            agents_used=[],
            workflow_pattern=WorkflowPattern(pattern) if pattern in WorkflowPattern._value2member_map_ else WorkflowPattern.HIERARCHICAL,
            is_mock=False,
        )

    # ── Create Blackboard Run ─────────────────────────────────────────
    run_id = bb.create_run(query, persona, pattern, conversation_id)
    bb.update_field(run_id, "sanitized_query", sanitized_query, "guardrails")
    metrics.start_run(run_id, pattern, sanitized_query)

    # ── Dispatch ─────────────────────────────────────────────────────
    pattern_upper = pattern.upper()
    try:
        if pattern_upper == "HIERARCHICAL":
            from app.workflows.hierarchical import run_hierarchical
            return run_hierarchical(query, sanitized_query, run_id, persona)
        elif pattern_upper == "PARALLEL":
            from app.workflows.parallel import run_parallel
            return run_parallel(query, sanitized_query, run_id, persona)
        elif pattern_upper == "SEQUENTIAL":
            from app.workflows.sequential import run_sequential
            return run_sequential(query, sanitized_query, run_id, persona)
        elif pattern_upper == "BASELINE":
            from app.workflows.baseline import run_baseline
            return run_baseline(query, sanitized_query, run_id, persona)
        else:
            logger.warning(f"Unknown pattern '{pattern}', using HIERARCHICAL")
            from app.workflows.hierarchical import run_hierarchical
            return run_hierarchical(query, sanitized_query, run_id, persona)
    except Exception as exc:
        logger.error(f"Workflow dispatch error: {exc}", exc_info=True)
        bb.update_field(run_id, "current_status", "FAILED", "workflow_engine")
        return FinalResponse(
            run_id=run_id,
            query=query,
            sanitized_query=sanitized_query,
            answer=f"System error — workflow could not complete: {str(exc)[:200]}",
            verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            limitations=[str(exc)[:300]],
            agents_used=[],
            workflow_pattern=WorkflowPattern.HIERARCHICAL,
            is_mock=not settings.has_llm_configured(),
        )
    finally:
        metrics.finish_run(run_id)

