"""
CrewAI Critic / Verification Agent.
Checks claims against evidence, identifies unsupported assertions,
and returns structured validation results.

Framework: CrewAI
"""
from __future__ import annotations

import logging

from crewai import Agent, LLM

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

CRITIC_INSTRUCTIONS = """
You are a rigorous fact-checker and verification specialist.

Your job:
1. Review the research findings and draft answer.
2. Check each key claim against provided evidence (web results, document excerpts, data).
3. Identify:
   - Unsupported claims (no evidence cited)
   - Contradictions (evidence conflicts with claim)
   - Missing citations (claim needs a source)
   - Insufficient evidence (evidence is weak or tangential)
4. Return a structured verdict: PASS, NEEDS_REVISION, or INSUFFICIENT_EVIDENCE.
5. For NEEDS_REVISION or INSUFFICIENT_EVIDENCE, specify exactly which claims are problematic
   and why. Recommend specific corrections.

IMPORTANT RULES:
- Do NOT treat LLM confidence as evidence of correctness.
- Only mark a claim as supported if there is explicit evidence in the provided context.
- Do not reject claims simply because they are complex or surprising — only reject if
  the provided evidence contradicts them or there is NO evidence.
- Be specific about what is missing.
- Format your response as:
  VERDICT: [PASS|NEEDS_REVISION|INSUFFICIENT_EVIDENCE]
  ISSUES: [list each specific issue]
  RECOMMENDATIONS: [specific corrections needed]
"""


def build_critic_agent(llm=None) -> Agent:
    """Create and return the CrewAI Critic Agent."""
    settings = get_settings()
    if llm is None:
        llm = settings.get_crewai_llm()

    return Agent(
        role="Research Critic and Fact-Checker",
        goal=(
            "Verify research claims against provided evidence. Identify unsupported assertions, "
            "contradictions, and missing citations. Produce a structured PASS/NEEDS_REVISION/"
            "INSUFFICIENT_EVIDENCE verdict with specific actionable feedback."
        ),
        backstory=(
            "You are a meticulous academic fact-checker who never accepts claims at face value. "
            "You demand evidence for every assertion. You are constructive — you explain exactly "
            "what is missing and suggest how to fix it. You never fabricate evidence or pretend "
            "a claim is supported when it is not. LLM confidence is not evidence."
        ),
        tools=[],  # Critic reasons over provided context — no external tools needed
        verbose=True,
        allow_delegation=False,
        llm=llm,
        max_iter=3,
        memory=False,
    )


def parse_critic_output(output: str) -> dict:
    """
    Parse the critic agent's free-form output into a structured result.
    Returns: {verdict, issues, recommendations, raw_output}
    """
    output = output.strip()
    verdict = "PENDING"
    issues = []
    recommendations = []

    lines = output.split("\n")
    current_section = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("VERDICT:"):
            v = line.replace("VERDICT:", "").strip().upper()
            for valid in ["PASS", "NEEDS_REVISION", "INSUFFICIENT_EVIDENCE"]:
                if valid in v:
                    verdict = valid
                    break
        elif line.startswith("ISSUES:"):
            current_section = "issues"
        elif line.startswith("RECOMMENDATIONS:"):
            current_section = "recommendations"
        elif current_section == "issues" and line:
            # Strip list markers
            clean = line.lstrip("- •*123456789.").strip()
            if clean:
                issues.append(clean)
        elif current_section == "recommendations" and line:
            clean = line.lstrip("- •*123456789.").strip()
            if clean:
                recommendations.append(clean)

    # Fallback: if we couldn't parse, infer from content
    if verdict == "PENDING":
        if "pass" in output.lower() and "fail" not in output.lower():
            verdict = "PASS"
        elif any(kw in output.lower() for kw in ["insufficient", "missing", "no evidence"]):
            verdict = "INSUFFICIENT_EVIDENCE"
        else:
            verdict = "NEEDS_REVISION"

    return {
        "verdict": verdict,
        "issues": issues,
        "recommendations": recommendations,
        "raw_output": output[:2000],
    }

