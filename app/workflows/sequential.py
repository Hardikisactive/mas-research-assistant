"""
Sequential Workflow — Strict chain: RAG → Verify → Synthesize.
Best for document-centric questions where evidence must precede synthesis.
"""
from __future__ import annotations
import json, logging, time
from typing import Any
from crewai import Crew, Task, Process
from app.agents.critic.agent import build_critic_agent, parse_critic_output
from app.agents.synthesis.agent import build_synthesis_agent
from app.protocols.a2a.client import A2ARagTool
from app.state.blackboard import get_blackboard
from app.observability.metrics import get_metrics
from app.config.settings import get_settings
from app.schemas.outputs import FinalResponse
from app.schemas.base import (VerificationStatus, WorkflowPattern, ExecutionSummary)

logger = logging.getLogger(__name__)


def _kickoff_with_retry(crew: Crew, label: str, max_retries: int = 3) -> Any:
    """Retry crew.kickoff() on 503/transient errors with exponential backoff."""
    delays = [15, 30, 60]
    for attempt in range(max_retries + 1):
        try:
            return crew.kickoff()
        except Exception as exc:
            err_str = str(exc)
            is_transient = any(code in err_str for code in [
                "503", "UNAVAILABLE", "429", "RATE_LIMIT",
                "Server disconnected", "Connection reset", "timeout",
            ])
            if is_transient and attempt < max_retries:
                wait = delays[min(attempt, len(delays) - 1)]
                logger.warning(
                    f"[{label}] Transient error (attempt {attempt+1}/{max_retries}), "
                    f"retrying in {wait}s: {err_str[:120]}"
                )
                time.sleep(wait)
            else:
                raise


def run_sequential(
    query: str,
    sanitized_query: str,
    run_id: str,
    persona: str = "RESEARCHER",
) -> FinalResponse:
    """
    Execute the sequential workflow: RAG → Critic → Synthesis (in strict order).
    Each step depends on the previous step's output.
    """
    bb = get_blackboard()
    metrics = get_metrics()
    settings = get_settings()
    start = time.perf_counter()
    is_mock = settings.get_crewai_llm() is None

    bb.update_field(run_id, "current_status", "RUNNING", "sequential_workflow")
    bb.record_event(run_id, "sequential_workflow", "started", "RUNNING",
                    f"Sequential: {sanitized_query[:80]}")

    agents_used = []

    try:
        # Step 1: RAG (Document Retrieval via A2A)
        rag_tool = A2ARagTool()
        t_start = time.perf_counter()
        bb.record_event(run_id, "rag_agent", "started", "RUNNING", "Step 1: RAG")
        rag_raw = rag_tool._run(sanitized_query)
        dur = (time.perf_counter() - t_start) * 1000
        try:
            rag_context = json.loads(rag_raw).get("answer", rag_raw)
        except Exception:
            rag_context = rag_raw
        agents_used.append("rag_agent")
        bb.record_event(run_id, "rag_agent", "completed", "SUCCESS",
                        rag_context[:200], duration_ms=dur)
        bb.update_dict_field(run_id, "agent_outputs", "rag", rag_context[:1000], "rag_agent")
        metrics.record_a2a(run_id, success=True)

        # Step 2: Critic verifies retrieved evidence
        if not is_mock:
            llm = settings.get_crewai_llm()
            critic = build_critic_agent(llm)
            t_crit = Task(
                description=(
                    f"Evaluate quality and relevance of retrieved evidence for: {sanitized_query}\n"
                    f"Evidence retrieved:\n{rag_context[:2000]}\n"
                    f"Are these chunks relevant? Any missing context? State PASS if sufficient."
                ),
                expected_output="VERDICT: PASS|NEEDS_REVISION|INSUFFICIENT_EVIDENCE\nISSUES:\nRECOMMENDATIONS:",
                agent=critic,
            )
            t_start = time.perf_counter()
            bb.record_event(run_id, "critic_agent", "started", "RUNNING", "Step 2: Verify evidence")
            crew_c = Crew(agents=[critic], tasks=[t_crit],
                          process=Process.sequential, verbose=False)
            crit_raw = str(_kickoff_with_retry(crew_c, "critic_agent"))
            dur = (time.perf_counter() - t_start) * 1000
            crit_parsed = parse_critic_output(crit_raw)
            agents_used.append("critic_agent")
            bb.record_event(run_id, "critic_agent", "completed", "SUCCESS",
                            f"Verdict: {crit_parsed['verdict']}", duration_ms=dur)

            # Step 3: Synthesis (using verified evidence)
            synthesis = build_synthesis_agent(llm)
            t_synth = Task(
                description=(
                    f"Based on the following verified evidence, answer: {sanitized_query}\n\n"
                    f"Evidence:\n{rag_context[:3000]}\n\n"
                    f"Critic notes: {crit_parsed.get('issues', [])}"
                ),
                expected_output="Comprehensive answer citing document evidence with limitations.",
                agent=synthesis,
            )
            t_start = time.perf_counter()
            bb.record_event(run_id, "synthesis_agent", "started", "RUNNING", "Step 3: Synthesize")
            crew_s = Crew(agents=[synthesis], tasks=[t_synth],
                          process=Process.sequential, verbose=False)
            final_answer = str(_kickoff_with_retry(crew_s, "synthesis_agent"))
            dur = (time.perf_counter() - t_start) * 1000
            agents_used.append("synthesis_agent")
            bb.record_event(run_id, "synthesis_agent", "completed", "SUCCESS",
                            final_answer[:200], duration_ms=dur)

            verdict = {
                "PASS": VerificationStatus.PASS,
                "NEEDS_REVISION": VerificationStatus.NEEDS_REVISION,
                "INSUFFICIENT_EVIDENCE": VerificationStatus.INSUFFICIENT_EVIDENCE,
            }.get(crit_parsed["verdict"], VerificationStatus.PENDING)
        else:
            final_answer = (
                f"[Mock] Sequential answer for: {sanitized_query}\n"
                f"Document evidence: {rag_context[:400]}"
            )
            verdict = VerificationStatus.PENDING

        total_ms = (time.perf_counter() - start) * 1000
        bb.update_field(run_id, "current_status", "COMPLETED", "sequential_workflow")
        bb.record_event(run_id, "sequential_workflow", "completed", "SUCCESS",
                        f"Done in {total_ms:.0f}ms", duration_ms=total_ms)

        return FinalResponse(
            run_id=run_id,
            query=query,
            sanitized_query=sanitized_query,
            answer=final_answer,
            verification_status=verdict,
            limitations=["Mock mode"] if is_mock else [],
            agents_used=agents_used,
            workflow_pattern=WorkflowPattern.SEQUENTIAL,
            execution_summary=ExecutionSummary(
                total_duration_ms=total_ms,
                agent_count=len(agents_used),
                a2a_calls=1,
            ),
            is_mock=is_mock,
        )

    except Exception as exc:
        total_ms = (time.perf_counter() - start) * 1000
        logger.error(f"Sequential workflow error: {exc}", exc_info=True)
        bb.update_field(run_id, "current_status", "FAILED", "sequential_workflow")
        return FinalResponse(
            run_id=run_id, query=query, sanitized_query=sanitized_query,
            answer=f"Sequential workflow failed: {exc}",
            verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            limitations=[str(exc)[:200]],
            agents_used=agents_used,
            workflow_pattern=WorkflowPattern.SEQUENTIAL,
            execution_summary=ExecutionSummary(total_duration_ms=total_ms),
            is_mock=is_mock,
        )

