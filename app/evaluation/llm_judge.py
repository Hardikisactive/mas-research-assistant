"""
LLM-as-Judge — uses Gemini to semantically evaluate system answers.

Instead of keyword matching, the judge LLM reads the question,
the reference answer, and the system's actual answer, then scores:
  - correctness   (0-10): Is the answer factually right?
  - relevance     (0-10): Does it address what was asked?
  - completeness  (0-10): Is it thorough enough?
  - overall       (0-10): Overall quality score

Returns a JudgeResult with numeric scores + a brief reasoning string.

Usage (standalone):
    from app.evaluation.llm_judge import judge_answer
    result = judge_answer(
        query="What is the speed of light?",
        reference="299,792,458 metres per second",
        actual="The speed of light is approximately 3×10^8 m/s.",
    )
    print(result.overall_score)   # e.g. 8.5

Usage (in harness — called automatically when use_llm_judge=True):
    records = run_evaluation(patterns=["HIERARCHICAL"], limit=5, use_llm_judge=True)
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from pydantic import BaseModel, Field

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


# ── Output schema ──────────────────────────────────────────────────────────────

class JudgeResult(BaseModel):
    """Scores returned by the LLM judge for one answer."""

    correctness: Optional[float] = Field(None, ge=0, le=10,
        description="Factual accuracy vs reference answer (0-10)")
    relevance: Optional[float] = Field(None, ge=0, le=10,
        description="How well the answer addresses the question (0-10)")
    completeness: Optional[float] = Field(None, ge=0, le=10,
        description="Thoroughness of the answer (0-10)")
    overall_score: Optional[float] = Field(None, ge=0, le=10,
        description="Overall quality score 0-10")
    reasoning: str = ""
    judge_model: str = ""
    is_mock: bool = False
    error: Optional[str] = None

    @property
    def normalized_overall(self) -> Optional[float]:
        """Return overall_score as 0-1 float (for comparison with heuristic scores)."""
        if self.overall_score is None:
            return None
        return round(self.overall_score / 10, 3)


# ── Prompt ─────────────────────────────────────────────────────────────────────

_JUDGE_PROMPT = """You are an expert evaluator for an AI research assistant system.
Your job is to fairly score the SYSTEM ANSWER against a REFERENCE ANSWER for a given QUESTION.

QUESTION:
{query}

REFERENCE ANSWER (ground truth):
{reference}

SYSTEM ANSWER (what the AI produced):
{actual}

Please evaluate the SYSTEM ANSWER on these 4 dimensions (each 0-10):

1. CORRECTNESS (0-10): Is the information factually accurate compared to the reference?
   - 10 = perfectly correct, matches reference fully
   - 5  = partially correct, some errors or omissions
   - 0  = completely wrong or unrelated

2. RELEVANCE (0-10): Does the answer actually address the question asked?
   - 10 = directly answers the question
   - 5  = tangentially related but misses the point
   - 0  = completely off-topic

3. COMPLETENESS (0-10): Is the answer sufficiently thorough?
   - 10 = covers all key aspects from the reference
   - 5  = covers about half of what was needed
   - 0  = almost nothing covered

4. OVERALL (0-10): Your holistic quality assessment.

IMPORTANT: You MUST respond ONLY with valid JSON in this exact format:
{{
  "correctness": <number 0-10>,
  "relevance": <number 0-10>,
  "completeness": <number 0-10>,
  "overall": <number 0-10>,
  "reasoning": "<one or two sentences explaining your scores>"
}}

No extra text. Only the JSON object."""


# ── Core function ──────────────────────────────────────────────────────────────

def judge_answer(
    query: str,
    actual: str,
    reference: Optional[str] = None,
    timeout_seconds: int = 30,
) -> JudgeResult:
    """
    Use Gemini as a judge to score the system's answer.

    Args:
        query:    The original user question.
        actual:   The answer produced by the MAS system.
        reference: The ground-truth reference answer (from test cases).
        timeout_seconds: Max seconds to wait for the judge response.

    Returns:
        JudgeResult with correctness, relevance, completeness, overall_score, reasoning.
        Falls back to is_mock=True with None scores if API key unavailable or error occurs.
    """
    settings = get_settings()

    # ── No reference → can't judge correctness properly ───────────────────────
    if not reference or reference in {"rejected", "rejected_empty",
                                      "rejected_too_long", "insufficient_evidence"}:
        return JudgeResult(
            reasoning="No reference answer available — LLM judge skipped.",
            judge_model="none",
            is_mock=True,
        )

    # ── No API key → mock result ───────────────────────────────────────────────
    if not settings.google_api_key:
        return JudgeResult(
            reasoning="No GOOGLE_API_KEY configured — LLM judge unavailable.",
            judge_model="mock",
            is_mock=True,
        )

    prompt = _JUDGE_PROMPT.format(
        query=query.strip(),
        reference=reference.strip()[:800],
        actual=actual.strip()[:1200],
    )

    start = time.perf_counter()
    model_name = settings.adk_model  # e.g. "gemini-3.1-flash-lite"

    try:
        # Use google-genai (new SDK, already installed by ADK)
        from google import genai as new_genai  # type: ignore
        client = new_genai.Client(api_key=settings.google_api_key)
        resp = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=new_genai.types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=256,
            ),
        )
        raw_text = resp.text.strip()
        duration = (time.perf_counter() - start) * 1000
        logger.debug(f"LLM judge raw response ({duration:.0f}ms): {raw_text[:200]}")

    except Exception as exc:
        logger.error(f"LLM judge API error: {exc}")
        return JudgeResult(error=str(exc)[:200], is_mock=True, judge_model=model_name)

    # ── Parse JSON from response ───────────────────────────────────────────────
    try:
        # Strip markdown code fences if present
        clean = re.sub(r"```(?:json)?", "", raw_text).strip().rstrip("```").strip()
        # Find the first JSON object in the response
        m = re.search(r'\{.*\}', clean, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON object found in judge response: {raw_text[:100]}")
        data = json.loads(m.group())

        return JudgeResult(
            correctness=float(data.get("correctness", 0)),
            relevance=float(data.get("relevance", 0)),
            completeness=float(data.get("completeness", 0)),
            overall_score=float(data.get("overall", 0)),
            reasoning=str(data.get("reasoning", ""))[:500],
            judge_model=model_name,
            is_mock=False,
        )

    except Exception as exc:
        logger.warning(f"LLM judge JSON parse error: {exc} | raw: {raw_text[:150]}")
        return JudgeResult(
            error=f"JSON parse failed: {exc}",
            reasoning=raw_text[:300],
            judge_model=model_name,
            is_mock=True,
        )


# ── Batch helper ───────────────────────────────────────────────────────────────

def judge_records_batch(
    records: list[dict],
    delay_between_calls: float = 2.0,
) -> list[dict]:
    """
    Run LLM-as-judge on a list of EvaluationRecord dicts (already saved to JSON).
    Adds llm_judge_* fields to each record and returns the updated list.

    Args:
        records: List of dicts loaded from eval_*.json files.
        delay_between_calls: Seconds to wait between judge API calls (avoid rate limits).

    Returns:
        Updated list with llm_judge_correctness, llm_judge_relevance,
        llm_judge_completeness, llm_judge_overall, llm_judge_reasoning added.
    """
    total = len(records)
    logger.info(f"Running LLM judge on {total} records...")

    for i, rec in enumerate(records, 1):
        query = rec.get("query", "")
        actual = rec.get("actual_answer", "")
        reference = rec.get("reference_answer")

        # Skip if already judged
        if rec.get("llm_judge_overall") is not None:
            continue

        # Skip error runs
        if rec.get("error_occurred") or not actual or actual.startswith("ERROR:"):
            rec["llm_judge_overall"] = None
            rec["llm_judge_reasoning"] = "Skipped — error run"
            continue

        logger.info(f"  Judging [{i}/{total}]: {query[:60]}...")
        result = judge_answer(query=query, actual=actual, reference=reference)

        rec["llm_judge_correctness"] = result.correctness
        rec["llm_judge_relevance"] = result.relevance
        rec["llm_judge_completeness"] = result.completeness
        rec["llm_judge_overall"] = result.overall_score
        rec["llm_judge_overall_normalized"] = result.normalized_overall
        rec["llm_judge_reasoning"] = result.reasoning
        rec["llm_judge_model"] = result.judge_model
        rec["llm_judge_is_mock"] = result.is_mock

        if i < total:
            time.sleep(delay_between_calls)

    logger.info("LLM judge batch complete.")
    return records


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Quick test
    test_query = "What is the speed of light in a vacuum?"
    test_ref = "299,792,458 metres per second (approximately 3×10^8 m/s)"
    test_actual = "The speed of light is about 300,000 kilometres per second or 3×10^8 m/s in vacuum."

    print("Running LLM-as-Judge test...")
    result = judge_answer(query=test_query, reference=test_ref, actual=test_actual)
    print(f"\nJudge Result:")
    print(f"  Correctness:   {result.correctness}/10")
    print(f"  Relevance:     {result.relevance}/10")
    print(f"  Completeness:  {result.completeness}/10")
    print(f"  Overall:       {result.overall_score}/10  (normalized: {result.normalized_overall})")
    print(f"  Reasoning:     {result.reasoning}")
    print(f"  Model used:    {result.judge_model}")
    print(f"  Is mock:       {result.is_mock}")
