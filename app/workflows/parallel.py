"""
Parallel Workflow — Research and RAG run concurrently via threading.
Pattern: [Research ‖ RAG] → merge → Critic → Synthesis
"""
from __future__ import annotations
import json, logging, time, threading
from typing import Optional, Any
from crewai import Crew, Task, Process
from app.agents.research.agent import build_research_agent
from app.agents.critic.agent import build_critic_agent, parse_critic_output
from app.agents.synthesis.agent import build_synthesis_agent
from app.agents.supervisor.agent import classify_query
from app.protocols.a2a.client import A2ARagTool
from app.state.blackboard import get_blackboard
from app.observability.metrics import get_metrics
from app.config.settings import get_settings
from app.schemas.outputs import FinalResponse
from app.schemas.base import (VerificationStatus, WorkflowPattern, Finding,
                               ExecutionSummary)

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


def run_parallel(
    query: str,
    sanitized_query: str,
    run_id: str,
    persona: str = "RESEARCHER",
) -> FinalResponse:
    """
    Execute the parallel workflow.
    Research and RAG retrieval run concurrently; results are merged before synthesis.
    """
    bb = get_blackboard()
    metrics = get_metrics()
    settings = get_settings()
    start = time.perf_counter()
    is_mock = settings.get_crewai_llm() is None

    bb.update_field(run_id, "current_status", "RUNNING", "parallel_workflow")
    bb.record_event(run_id, "parallel_workflow", "started", "RUNNING",
                    f"Parallel: {sanitized_query[:80]}")

    agents_used = []
    results: dict = {"research": "", "rag": "", "errors": []}
    lock = threading.Lock()

    def _run_research():
        if is_mock:
            with lock:
                results["research"] = f"[Mock] Web research for: {sanitized_query}"
            return
        try:
            llm = settings.get_crewai_llm()
            researcher = build_research_agent(llm)
            t = Task(
                description=f"Search web for: {sanitized_query}. Return top 5 sources with excerpts.",
                expected_output="Source list with titles, URLs, key facts.",
                agent=researcher,
            )
            t_start = time.perf_counter()
            bb.record_event(run_id, "research_agent", "started", "RUNNING",
                            "Parallel web search")
            crew = Crew(agents=[researcher], tasks=[t],
                        process=Process.sequential, verbose=False)
            r = _kickoff_with_retry(crew, "research_agent")
            dur = (time.perf_counter() - t_start) * 1000
            with lock:
                results["research"] = str(r)
                agents_used.append("research_agent")
            bb.record_event(run_id, "research_agent", "completed", "SUCCESS",
                            str(r)[:200], duration_ms=dur)
            metrics.record_agent(run_id, "research_agent", dur)
        except Exception as exc:
            with lock:
                results["errors"].append(f"research: {exc}")
            bb.record_event(run_id, "research_agent", "failed", "FAILED", str(exc)[:200])
            logger.error(f"Parallel research error: {exc}")

    def _run_rag():
        try:
            rag_tool = A2ARagTool()
            t_start = time.perf_counter()
            bb.record_event(run_id, "rag_agent", "started", "RUNNING", "Parallel A2A RAG")
            raw = rag_tool._run(sanitized_query)
            dur = (time.perf_counter() - t_start) * 1000
            try:
                rag_data = json.loads(raw)
                rag_text = rag_data.get("answer", raw)
            except Exception:
                rag_text = raw
            with lock:
                results["rag"] = rag_text
                agents_used.append("rag_agent")
            bb.record_event(run_id, "rag_agent", "completed", "SUCCESS",
                            rag_text[:200], duration_ms=dur)
            metrics.record_a2a(run_id, success=True)
        except Exception as exc:
            with lock:
                results["errors"].append(f"rag: {exc}")
            bb.record_event(run_id, "rag_agent", "failed", "FAILED", str(exc)[:200])
            logger.error(f"Parallel RAG error: {exc}")

    # ── Launch parallel threads ───────────────────────────────────────
    t1 = threading.Thread(target=_run_research, daemon=True)
    t2 = threading.Thread(target=_run_rag, daemon=True)
    t1.start(); t2.start()
    t1.join(timeout=90); t2.join(timeout=90)

    combined = "\n\n".join(filter(None, [
        f"Web Research:\n{results['research']}" if results["research"] else "",
        f"Document Evidence:\n{results['rag']}" if results["rag"] else "",
    ])) or f"Query: {sanitized_query} (no evidence retrieved)"

    bb.update_dict_field(run_id, "agent_outputs", "parallel_combined",
                         combined[:2000], "parallel_workflow")

    try:
        if not is_mock:
            llm = settings.get_crewai_llm()
            synthesis = build_synthesis_agent(llm)
            critic = build_critic_agent(llm)

            t_synth = Task(
                description=(
                    f"Synthesize for: {sanitized_query}\n\n{combined}"
                ),
                expected_output="Comprehensive cited answer with limitations stated.",
                agent=synthesis,
            )
            crew_s = Crew(agents=[synthesis], tasks=[t_synth],
                          process=Process.sequential, verbose=False)
            synth_out = str(_kickoff_with_retry(crew_s, "synthesis_agent"))
            agents_used.append("synthesis_agent")

            t_crit = Task(
                description=(
                    f"Verify: {sanitized_query}\nAnswer:\n{synth_out}\n"
                    f"Evidence:\n{combined[:2000]}"
                ),
                expected_output="VERDICT: PASS|NEEDS_REVISION|INSUFFICIENT_EVIDENCE\nISSUES:\nRECOMMENDATIONS:",
                agent=critic,
            )
            crew_c = Crew(agents=[critic], tasks=[t_crit],
                          process=Process.sequential, verbose=False)
            crit_out = parse_critic_output(str(_kickoff_with_retry(crew_c, "critic_agent")))
            agents_used.append("critic_agent")

            verdict = {
                "PASS": VerificationStatus.PASS,
                "NEEDS_REVISION": VerificationStatus.NEEDS_REVISION,
                "INSUFFICIENT_EVIDENCE": VerificationStatus.INSUFFICIENT_EVIDENCE,
            }.get(crit_out["verdict"], VerificationStatus.PENDING)
            final_answer = synth_out
        else:
            final_answer = f"[Mock] Parallel synthesis for: {sanitized_query}\n\n{combined[:500]}"
            verdict = VerificationStatus.PENDING

    except Exception as exc:
        logger.error(f"Parallel synthesis/critic error: {exc}")
        final_answer = f"Partial result (synthesis failed): {combined[:500]}"
        verdict = VerificationStatus.INSUFFICIENT_EVIDENCE

    total_ms = (time.perf_counter() - start) * 1000
    bb.update_field(run_id, "current_status", "COMPLETED", "parallel_workflow")
    bb.record_event(run_id, "parallel_workflow", "completed", "SUCCESS",
                    f"Done in {total_ms:.0f}ms", duration_ms=total_ms)

    return FinalResponse(
        run_id=run_id,
        query=query,
        sanitized_query=sanitized_query,
        answer=final_answer,
        verification_status=verdict,
        limitations=(["Mock mode"] if is_mock else results["errors"][:3]),
        agents_used=agents_used,
        workflow_pattern=WorkflowPattern.PARALLEL,
        execution_summary=ExecutionSummary(
            total_duration_ms=total_ms,
            agent_count=len(agents_used),
            a2a_calls=1,
        ),
        is_mock=is_mock,
    )

