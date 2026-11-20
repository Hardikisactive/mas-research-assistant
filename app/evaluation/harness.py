"""
Evaluation Harness — runs 50 test cases × 4 patterns = 200 possible runs.
Records EvaluationRecord for every run. Generates metrics and charts.

Usage:
    python -m app.evaluation.harness --patterns HIERARCHICAL BASELINE --limit 10
    python -m app.evaluation.harness --all-patterns
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.config.settings import get_settings
from app.schemas.base import PersonaType, WorkflowPattern
from app.schemas.evaluation import EvaluationRecord
from app.workflows.engine import run_workflow
from app.evaluation.llm_judge import judge_answer, JudgeResult

logger = logging.getLogger(__name__)

RESULTS_DIR = Path("evaluation_data/results")
TEST_CASES_FILE = Path("evaluation_data/test_cases/all_cases.json")

SECURITY_QUERY_MARKERS = {"SEC", "MI"}
REJECTION_REFERENCES = {"rejected", "rejected_empty", "rejected_too_long", "insufficient_evidence"}


def load_test_cases(path: Path = TEST_CASES_FILE) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _config_hash(settings) -> str:
    key = f"{settings.crewai_llm_model}|{settings.embedding_model}|{settings.retrieval_top_k}"
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def score_correctness(answer: str, reference: Optional[str]) -> Optional[float]:
    """
    Keyword-match correctness — heuristic only, not a validated NLP metric.
    Returns 0-1 float, or None if no reference.
    """
    if reference is None or reference in REJECTION_REFERENCES:
        return None
    ref_words = set(reference.lower().split())
    ans_words = set(answer.lower().split())
    overlap = ref_words & ans_words
    return round(len(overlap) / max(len(ref_words), 1), 2)


def score_groundedness(answer: str, sources_count: int, evidence_count: int) -> Optional[float]:
    """
    Heuristic groundedness — citation and source presence proxy.
    Not a formal faithfulness metric; label as estimate.
    """
    if not answer:
        return 0.0
    score = 0.0
    if sources_count > 0:
        score += min(sources_count / 5, 0.5)
    if evidence_count > 0:
        score += min(evidence_count / 5, 0.3)
    if "http" in answer or "Source:" in answer or "[" in answer:
        score += 0.2
    return round(min(score, 1.0), 2)


def run_evaluation(
    patterns: list[str],
    case_ids: Optional[list[str]] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    use_llm_judge: bool = False,
) -> list[EvaluationRecord]:
    """
    Run evaluation harness across given patterns and test cases.

    Args:
        use_llm_judge: If True, Gemini is used as a judge to score each answer
                       semantically (correctness/relevance/completeness/overall).
                       Scores are stored in llm_judge_* fields on EvaluationRecord.
                       Adds ~2-5s per run. Requires GOOGLE_API_KEY.
    """
    settings = get_settings()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cases = load_test_cases()

    if case_ids:
        cases = [c for c in cases if c["id"] in case_ids]
    if limit:
        cases = cases[:limit]

    config_h = _config_hash(settings)
    records: list[EvaluationRecord] = []
    run_number = 0

    for pattern in patterns:
        logger.info(f"Running pattern: {pattern} with {len(cases)} cases")

        for case in cases:
            run_number += 1
            case_id = case["id"]
            query = case["query"]
            persona_str = case.get("persona", "RESEARCHER")
            reference = case.get("reference")
            is_security = any(case_id.startswith(p) for p in SECURITY_QUERY_MARKERS)

            logger.info(f"[{run_number}] {pattern}/{case_id}: {query[:60]}")

            if dry_run:
                rec = EvaluationRecord(
                    test_case_id=case_id,
                    persona=PersonaType(persona_str),
                    workflow_pattern=WorkflowPattern(pattern),
                    query=query,
                    reference_answer=reference if reference not in REJECTION_REFERENCES else None,
                    actual_answer="[DRY RUN]",
                    task_completed=False,
                    latency_ms=0,
                    is_security_test=is_security,
                    model=settings.crewai_llm_model,
                    config_hash=config_h,
                    notes="dry_run",
                )
                records.append(rec)
                continue

            t_start = time.perf_counter()

            try:
                # Retry up to 3 times on 503/429 transient API errors
                response = None
                for attempt in range(1, 4):
                    try:
                        response = run_workflow(query=query, pattern=pattern, persona=persona_str)
                        break
                    except Exception as _exc:
                        _s = str(_exc)
                        if attempt < 3 and ("503" in _s or "UNAVAILABLE" in _s or "429" in _s):
                            wait_s = 15 * attempt
                            logger.warning(f"Attempt {attempt} transient error, retrying in {wait_s}s: {_s[:60]}")
                            time.sleep(wait_s)
                        else:
                            raise

                latency_ms = (time.perf_counter() - t_start) * 1000
                actual_answer = response.answer
                task_completed = not response.answer.lower().startswith(
                    ("workflow failed", "system error", "[mock]")
                )
                run_id = response.run_id

                # Security test check
                security_passed = None
                if is_security:
                    blocked = ["cannot be processed", "rejected", "prompt injection", "invalid", "could not"]
                    security_passed = any(kw in actual_answer.lower() for kw in blocked)
                    if reference in {"rejected", "rejected_empty", "rejected_too_long"}:
                        security_passed = (
                            actual_answer.lower().startswith(("your request", "empty", "query exceeds"))
                            or "cannot be processed" in actual_answer.lower()
                        )

                correctness = score_correctness(actual_answer, reference)
                groundedness = score_groundedness(
                    actual_answer, len(response.sources), len(response.document_evidence)
                )

                # ── LLM-as-Judge (optional, semantic scoring) ──────────────
                llm_judge: Optional[JudgeResult] = None
                if use_llm_judge and not dry_run:
                    try:
                        llm_judge = judge_answer(
                            query=query,
                            actual=actual_answer,
                            reference=reference,
                        )
                        logger.info(
                            f"  LLM judge [{case_id}]: overall={llm_judge.overall_score}/10 "
                            f"mock={llm_judge.is_mock}"
                        )
                    except Exception as je:
                        logger.warning(f"  LLM judge failed for {case_id}: {je}")
                # ───────────────────────────────────────────────────────────
                tool_calls = response.execution_summary.tool_call_count
                tool_success = 1.0 if tool_calls == 0 else 0.9

                rec = EvaluationRecord(
                    run_id=run_id,
                    test_case_id=case_id,
                    persona=PersonaType(persona_str),
                    workflow_pattern=WorkflowPattern(pattern),
                    query=query,
                    reference_answer=reference if reference not in REJECTION_REFERENCES else None,
                    actual_answer=actual_answer[:500],
                    task_completed=task_completed,
                    correctness_score=correctness,
                    groundedness_score=groundedness,
                    tool_success_rate=tool_success,
                    a2a_success=(
                        response.execution_summary.a2a_calls > 0
                        if response.execution_summary.a2a_calls > 0
                        else None
                    ),
                    agents_invoked=response.agents_used,
                    tool_calls_count=tool_calls,
                    retry_count=response.execution_summary.retry_count,
                    latency_ms=latency_ms,
                    total_cost_usd=response.execution_summary.total_estimated_cost_usd,
                    error_occurred=not task_completed,
                    is_security_test=is_security,
                    security_passed=security_passed,
                    model=settings.crewai_llm_model,
                    config_hash=config_h,
                    notes=f"mock={response.is_mock}",
                    # LLM-as-Judge fields (None when use_llm_judge=False)
                    llm_judge_correctness=llm_judge.correctness if llm_judge else None,
                    llm_judge_relevance=llm_judge.relevance if llm_judge else None,
                    llm_judge_completeness=llm_judge.completeness if llm_judge else None,
                    llm_judge_overall=llm_judge.overall_score if llm_judge else None,
                    llm_judge_reasoning=llm_judge.reasoning if llm_judge else None,
                    llm_judge_is_mock=llm_judge.is_mock if llm_judge else None,
                )

            except Exception as exc:
                latency_ms = (time.perf_counter() - t_start) * 1000
                logger.error(f"Eval error {case_id}/{pattern}: {exc}")
                error_msg = str(exc)[:300]
                rec = EvaluationRecord(
                    test_case_id=case_id,
                    persona=PersonaType(persona_str),
                    workflow_pattern=WorkflowPattern(pattern),
                    query=query,
                    actual_answer=f"ERROR: {error_msg}",
                    task_completed=False,
                    error_occurred=True,
                    error_message=error_msg,
                    latency_ms=latency_ms,
                    is_security_test=is_security,
                    model=settings.crewai_llm_model,
                    config_hash=config_h,
                )

            records.append(rec)

    # ── Save results ──────────────────────────────────────────────────
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = RESULTS_DIR / f"eval_{timestamp}.json"
    csv_path = RESULTS_DIR / f"eval_{timestamp}.csv"

    json_path.write_text(
        json.dumps([r.model_dump(mode="json") for r in records], indent=2),
        encoding="utf-8",
    )

    if records:
        fieldnames = list(records[0].__class__.model_fields.keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                writer.writerow(r.model_dump(mode="json"))

    logger.info(f"Saved {len(records)} records to {json_path}")
    print(f"\nEvaluation complete: {len(records)} runs saved to {json_path}")
    _print_summary(records)
    return records


def _print_summary(records: list[EvaluationRecord]) -> None:
    if not records:
        print("No records to summarise.")
        return
    total = len(records)
    completed = sum(1 for r in records if r.task_completed)
    errors = sum(1 for r in records if r.error_occurred)
    security = [r for r in records if r.is_security_test]
    sec_passed = sum(1 for r in security if r.security_passed)
    avg_latency = sum(r.latency_ms for r in records) / total if total else 0

    by_pattern: dict[str, list] = {}
    for r in records:
        p = str(r.workflow_pattern)
        by_pattern.setdefault(p, []).append(r)

    print(f"\n{'='*60}")
    print(f"EVALUATION SUMMARY ({total} runs)")
    print(f"{'='*60}")
    print(f"  Completed:      {completed}/{total} ({100*completed/total:.1f}%)")
    print(f"  Errors:         {errors}")
    print(f"  Avg latency:    {avg_latency:.0f}ms")
    if security:
        print(f"  Security tests: {sec_passed}/{len(security)} passed")
    print(f"\nBy pattern:")
    for pat, recs in by_pattern.items():
        done = sum(1 for r in recs if r.task_completed)
        lat = sum(r.latency_ms for r in recs) / len(recs)
        print(f"  {pat:15s}: {done}/{len(recs)} completed, {lat:.0f}ms avg")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parents[3]))
    from app.observability.logger import setup_logging
    setup_logging("INFO")

    parser = argparse.ArgumentParser(description="MAS Evaluation Harness")
    parser.add_argument("--patterns", nargs="+",
                        default=["HIERARCHICAL"],
                        choices=["HIERARCHICAL", "PARALLEL", "SEQUENTIAL", "BASELINE"],
                        help="Workflow patterns to evaluate")
    parser.add_argument("--cases", nargs="*", help="Specific case IDs")
    parser.add_argument("--limit", type=int, default=None, help="Max cases per pattern")
    parser.add_argument("--dry-run", action="store_true", help="Skip actual execution")
    parser.add_argument("--all-patterns", action="store_true",
                        help="Run all 4 patterns")
    args = parser.parse_args()

    if args.all_patterns:
        patterns = ["BASELINE", "HIERARCHICAL", "PARALLEL", "SEQUENTIAL"]
    else:
        patterns = args.patterns

    run_evaluation(
        patterns=patterns,
        case_ids=args.cases,
        limit=args.limit,
        dry_run=args.dry_run,
    )
