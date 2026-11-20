"""
Hierarchical Workflow — Supervisor delegates to specialists.
Pattern: Supervisor → [Research | RAG (via A2A)] → Critic → Synthesis
"""
from __future__ import annotations
import json, logging, time
from typing import Optional, Callable, Any
from crewai import Crew, Task, Process
from app.agents.supervisor.agent import build_supervisor_agent, classify_query
from app.agents.research.agent import build_research_agent
from app.agents.critic.agent import build_critic_agent, parse_critic_output
from app.agents.synthesis.agent import build_synthesis_agent
from app.agents.data_analysis.agent import build_data_analysis_agent
from app.protocols.a2a.client import A2ARagTool
from app.state.blackboard import get_blackboard
from app.observability.metrics import get_metrics
from app.config.settings import get_settings
from app.schemas.outputs import FinalResponse
from app.schemas.base import (VerificationStatus, WorkflowPattern, Finding,
                               SourceRecord, EvidenceRecord, ExecutionSummary, CostMetrics)

logger = logging.getLogger(__name__)


def _kickoff_with_retry(crew: Crew, label: str, max_retries: int = 3) -> Any:
    """
    Run crew.kickoff() with exponential backoff retry on 503/transient errors.
    Raises on non-retriable errors or after max_retries exhausted.
    """
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
                logger.error(f"[{label}] Failed after {attempt+1} attempt(s): {err_str[:200]}")
                raise


def _extract_sources_from_research(research_text: str) -> list[SourceRecord]:
    """
    Parse URLs and titles from the research agent's free-text output.
    The research agent outputs URLs inline — we extract them as SourceRecords.
    """
    import re
    sources = []
    seen_urls = set()

    # Match markdown links: [title](url) or bare URLs
    md_links = re.findall(r'\[([^\]]+)\]\((https?://[^\)]+)\)', research_text)
    for title, url in md_links:
        if url not in seen_urls:
            seen_urls.add(url)
            # Grab surrounding sentence as snippet (up to 200 chars)
            idx = research_text.find(url)
            snippet_start = max(0, idx - 80)
            snippet = research_text[snippet_start: idx + 120].strip()
            sources.append(SourceRecord(
                title=title.strip()[:200],
                url=url.strip(),
                snippet=snippet[:300],
                source_type="web",
            ))

    # Bare URLs not in markdown
    bare_urls = re.findall(r'(?<!\()https?://[^\s\)\]\,]+', research_text)
    for url in bare_urls:
        url = url.rstrip('.,;')
        if url not in seen_urls:
            seen_urls.add(url)
            idx = research_text.find(url)
            snippet_start = max(0, idx - 60)
            snippet = research_text[snippet_start: idx + 100].strip()
            # Guess title from URL domain
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.replace("www.", "")
            sources.append(SourceRecord(
                title=domain,
                url=url,
                snippet=snippet[:300],
                source_type="web",
            ))

    return sources[:10]  # Cap at 10 sources


def _extract_evidence_from_rag(rag_raw: str) -> tuple[str, list[EvidenceRecord]]:
    """
    Parse RAG JSON response and extract EvidenceRecords from chunks.
    Returns (answer_text, evidence_list).
    """
    evidence = []
    try:
        rag_data = json.loads(rag_raw)
        answer = rag_data.get("answer", rag_raw)
        chunks = rag_data.get("chunks", [])
        for chunk in chunks:
            if chunk.get("text"):
                evidence.append(EvidenceRecord(
                    document_id=chunk.get("document_id", ""),
                    chunk_id=chunk.get("chunk_id", ""),
                    text=chunk.get("text", "")[:500],
                    relevance_score=float(chunk.get("relevance_score", 0.0)),
                    page_number=chunk.get("page_number"),
                    filename=chunk.get("filename", ""),
                    chunk_index=int(chunk.get("chunk_index", 0)),
                ))
    except Exception:
        answer = rag_raw
    return answer, evidence



def run_hierarchical(
    query: str,
    sanitized_query: str,
    run_id: str,
    persona: str = "RESEARCHER",
) -> FinalResponse:
    """
    Execute the hierarchical workflow.
    Supervisor coordinates all agents sequentially with delegation.
    """
    bb = get_blackboard()
    metrics = get_metrics()
    settings = get_settings()
    start = time.perf_counter()

    bb.update_field(run_id, "current_status", "RUNNING", "hierarchical_workflow")
    bb.record_event(run_id, "hierarchical_workflow", "started", "RUNNING",
                    f"Query: {sanitized_query[:100]}")

    # Classify query to determine which agents to use
    classification = classify_query(sanitized_query)
    bb.update_field(run_id, "plan", classification, "supervisor")
    bb.update_field(run_id, "selected_agents", classification["agents_needed"], "supervisor")

    llm = settings.get_crewai_llm()
    is_mock = llm is None

    agents_used = []
    sources: list[SourceRecord] = []
    evidence: list[EvidenceRecord] = []
    findings: list[Finding] = []
    data_result = None
    critic_notes: list[str] = []

    try:
        if not is_mock:
            # ── Build agents ──────────────────────────────────────────
            supervisor = build_supervisor_agent(llm)
            researcher = build_research_agent(llm)
            critic = build_critic_agent(llm)
            synthesis = build_synthesis_agent(llm)

            # ── Task 1: Research ──────────────────────────────────────
            research_context = ""
            if "research" in classification["agents_needed"]:
                t_research = Task(
                    description=(
                        f"Search the web for information about: {sanitized_query}\n"
                        f"Collect 3-5 relevant sources with titles, URLs, and key excerpts.\n"
                        f"Distinguish facts from uncertain claims."
                    ),
                    expected_output=(
                        "A summary of web search findings with source URLs, "
                        "key facts extracted, and confidence notes."
                    ),
                    agent=researcher,
                )
                t_start = time.perf_counter()
                bb.record_event(run_id, "research_agent", "started", "RUNNING", "Web search")
                crew_r = Crew(agents=[researcher], tasks=[t_research],
                              process=Process.sequential, verbose=False)
                r_result = _kickoff_with_retry(crew_r, "research_agent")
                dur = (time.perf_counter() - t_start) * 1000
                research_context = str(r_result)
                # ── Extract sources from research text ────────────────
                extracted_sources = _extract_sources_from_research(research_context)
                # If no URLs found, add the research output as a text source
                if not extracted_sources and research_context.strip():
                    extracted_sources = [SourceRecord(
                        title=f"Research findings for: {sanitized_query[:60]}",
                        url="",
                        snippet=research_context[:400],
                        source_type="web",
                    )]
                sources.extend(extracted_sources)
                agents_used.append("research_agent")
                bb.record_event(run_id, "research_agent", "completed", "SUCCESS",
                                research_context[:200], duration_ms=dur)
                bb.update_dict_field(run_id, "agent_outputs", "research",
                                     research_context[:1000], "research_agent")
                metrics.record_agent(run_id, "research_agent", dur)

            # ── Task 2: RAG via A2A ───────────────────────────────────
            rag_context = ""
            if "rag" in classification["agents_needed"]:
                rag_tool = A2ARagTool()
                t_start = time.perf_counter()
                bb.record_event(run_id, "rag_agent", "started", "RUNNING",
                                "A2A RAG query")
                rag_raw = rag_tool._run(sanitized_query)
                dur = (time.perf_counter() - t_start) * 1000
                # ── Extract evidence chunks from RAG response ─────────
                rag_context, extracted_evidence = _extract_evidence_from_rag(rag_raw)
                evidence.extend(extracted_evidence)
                agents_used.append("rag_agent")
                bb.record_event(run_id, "rag_agent", "completed", "SUCCESS",
                                rag_context[:200], duration_ms=dur)
                bb.update_dict_field(run_id, "agent_outputs", "rag",
                                     rag_context[:1000], "rag_agent")
                metrics.record_a2a(run_id, success=True)

            # ── Task 3: Data Analysis ─────────────────────────────────
            data_context = ""
            if "data_analysis" in classification["agents_needed"]:
                data_agent = build_data_analysis_agent(llm)
                t_data = Task(
                    description=(
                        f"Analyze available CSV data relevant to: {sanitized_query}\n"
                        f"If no specific file is mentioned, look in the uploads directory."
                    ),
                    expected_output="Statistical summary, key metrics, and data insights.",
                    agent=data_agent,
                )
                t_start = time.perf_counter()
                bb.record_event(run_id, "data_analysis_agent", "started", "RUNNING", "Data analysis")
                crew_d = Crew(agents=[data_agent], tasks=[t_data],
                              process=Process.sequential, verbose=False)
                d_result = _kickoff_with_retry(crew_d, "data_analysis_agent")
                dur = (time.perf_counter() - t_start) * 1000
                data_context = str(d_result)
                agents_used.append("data_analysis_agent")
                bb.record_event(run_id, "data_analysis_agent", "completed", "SUCCESS",
                                data_context[:200], duration_ms=dur)
                bb.update_dict_field(run_id, "agent_outputs", "data_analysis",
                                     data_context[:1000], "data_analysis_agent")

            # ── Task 4: Synthesis ─────────────────────────────────────
            combined_context = "\n\n".join(filter(None, [
                f"Web Research:\n{research_context}" if research_context else "",
                f"Document Evidence:\n{rag_context}" if rag_context else "",
                f"Data Analysis:\n{data_context}" if data_context else "",
            ]))

            t_synthesis = Task(
                description=(
                    f"Synthesize the following research findings into a comprehensive answer "
                    f"for the query: {sanitized_query}\n\n{combined_context}"
                ),
                expected_output=(
                    "A well-structured, cited answer integrating all evidence. "
                    "State limitations where evidence is insufficient."
                ),
                agent=synthesis,
            )
            t_start = time.perf_counter()
            bb.record_event(run_id, "synthesis_agent", "started", "RUNNING", "Synthesizing")
            crew_s = Crew(agents=[synthesis], tasks=[t_synthesis],
                          process=Process.sequential, verbose=False)
            s_result = _kickoff_with_retry(crew_s, "synthesis_agent")
            dur = (time.perf_counter() - t_start) * 1000
            synthesis_text = str(s_result)
            agents_used.append("synthesis_agent")
            bb.record_event(run_id, "synthesis_agent", "completed", "SUCCESS",
                            synthesis_text[:200], duration_ms=dur)

            # ── Task 5: Critic ────────────────────────────────────────
            t_critic = Task(
                description=(
                    f"Verify the following answer against the evidence provided.\n"
                    f"Query: {sanitized_query}\n\n"
                    f"Answer to verify:\n{synthesis_text}\n\n"
                    f"Evidence available:\n{combined_context[:2000]}"
                ),
                expected_output=(
                    "VERDICT: [PASS|NEEDS_REVISION|INSUFFICIENT_EVIDENCE]\n"
                    "ISSUES: list of specific problems\n"
                    "RECOMMENDATIONS: specific corrections"
                ),
                agent=critic,
            )
            t_start = time.perf_counter()
            bb.record_event(run_id, "critic_agent", "started", "RUNNING", "Verifying")
            crew_c = Crew(agents=[critic], tasks=[t_critic],
                          process=Process.sequential, verbose=False)
            c_result = _kickoff_with_retry(crew_c, "critic_agent")
            dur = (time.perf_counter() - t_start) * 1000
            critic_parsed = parse_critic_output(str(c_result))
            agents_used.append("critic_agent")
            bb.record_event(run_id, "critic_agent", "completed", "SUCCESS",
                            f"Verdict: {critic_parsed['verdict']}", duration_ms=dur)
            bb.update_field(run_id, "critic_results", critic_parsed, "critic_agent")

            verdict_map = {
                "PASS": VerificationStatus.PASS,
                "NEEDS_REVISION": VerificationStatus.NEEDS_REVISION,
                "INSUFFICIENT_EVIDENCE": VerificationStatus.INSUFFICIENT_EVIDENCE,
            }
            verification_status = verdict_map.get(
                critic_parsed["verdict"], VerificationStatus.PENDING
            )
            critic_notes = critic_parsed.get("issues", [])

            # Build findings
            findings = [Finding(
                claim=synthesis_text[:300],
                verification_status=verification_status,
                confidence=0.8 if verification_status == VerificationStatus.PASS else 0.5,
            )]

            final_answer = synthesis_text

        else:
            # ── Mock mode ─────────────────────────────────────────────
            final_answer = (
                f"[MOCK MODE — No API key configured]\n\n"
                f"Query: {sanitized_query}\n\n"
                f"This is a stub response. To get real answers, set GOOGLE_API_KEY in .env\n"
                f"Classification: {classify_query(sanitized_query)}"
            )
            verification_status = VerificationStatus.PENDING
            agents_used = ["supervisor_mock"]

        total_ms = (time.perf_counter() - start) * 1000
        bb.update_field(run_id, "current_status", "COMPLETED", "hierarchical_workflow")
        bb.record_event(run_id, "hierarchical_workflow", "completed", "SUCCESS",
                        f"Done in {total_ms:.0f}ms", duration_ms=total_ms)
        metrics.record_agent(run_id, "hierarchical_workflow", total_ms)

        response = FinalResponse(
            run_id=run_id,
            query=query,
            sanitized_query=sanitized_query,
            answer=final_answer,
            key_findings=findings,
            sources=sources,
            document_evidence=evidence,
            verification_status=verification_status,
            limitations=(
                ["Running in mock mode — no real LLM calls"] if is_mock
                else critic_notes[:3] if critic_notes else []
            ),
            agents_used=agents_used,
            workflow_pattern=WorkflowPattern.HIERARCHICAL,
            execution_summary=ExecutionSummary(
                total_duration_ms=total_ms,
                agent_count=len(agents_used),
            ),
            is_mock=is_mock,
            critic_notes=critic_notes,
        )

        bb.update_field(run_id, "final_output",
                        response.model_dump(mode="json"), "hierarchical_workflow")
        return response

    except Exception as exc:
        total_ms = (time.perf_counter() - start) * 1000
        err_str = str(exc)
        logger.error(f"Hierarchical workflow error: {exc}", exc_info=True)
        bb.update_field(run_id, "current_status", "FAILED", "hierarchical_workflow")
        bb.append_to_list_field(run_id, "errors", err_str, "hierarchical_workflow")
        bb.record_event(run_id, "hierarchical_workflow", "failed", "FAILED",
                        err_str[:200], duration_ms=total_ms, error=err_str[:500])

        # User-friendly error messages for known transient failures
        if "503" in err_str or "UNAVAILABLE" in err_str:
            user_msg = (
                "⚠️ The AI model is currently overloaded (503 error). "
                "This is a temporary Google API issue.\n\n"
                "**Please try again in 30–60 seconds.** The system retried 3 times automatically.\n\n"
                "If the problem persists, try switching to the **BASELINE** or **SEQUENTIAL** "
                "workflow pattern from the sidebar."
            )
            limitation = "Google Gemini API returned 503 UNAVAILABLE (high demand). Retry later."
        elif "429" in err_str or "RATE_LIMIT" in err_str:
            user_msg = (
                "⚠️ Rate limit reached (429 error). Too many requests.\n\n"
                "**Please wait 1–2 minutes before trying again.**"
            )
            limitation = "API rate limit exceeded. Wait before retrying."
        else:
            user_msg = (
                f"⚠️ Workflow encountered an error.\n\n"
                f"**Details:** {err_str[:300]}\n\n"
                "Please try again or use a different workflow pattern."
            )
            limitation = err_str[:200]

        return FinalResponse(
            run_id=run_id,
            query=query,
            sanitized_query=sanitized_query,
            answer=user_msg,
            verification_status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            limitations=[limitation],
            agents_used=agents_used,
            workflow_pattern=WorkflowPattern.HIERARCHICAL,
            execution_summary=ExecutionSummary(total_duration_ms=total_ms),
            is_mock=is_mock,
        )

