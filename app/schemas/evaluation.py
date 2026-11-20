"""
Evaluation record schema for the 40+ run evaluation harness.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import PersonaType, WorkflowPattern, _now, _uid


class EvaluationRecord(BaseModel):
    """
    One row in the evaluation results CSV / database.
    Records all metrics for a single test run.
    """
    model_config = ConfigDict(use_enum_values=True)

    eval_id: str = Field(default_factory=_uid)
    run_id: str = ""
    test_case_id: str = ""
    persona: PersonaType = PersonaType.RESEARCHER
    workflow_pattern: WorkflowPattern = WorkflowPattern.HIERARCHICAL
    query: str = ""
    reference_answer: Optional[str] = None  # None if no ground truth available
    actual_answer: str = ""

    # Task outcome
    task_completed: bool = False
    correctness_score: Optional[float] = None   # 0-1, None if not evaluated
    groundedness_score: Optional[float] = None  # 0-1, None if not evaluated
    evidence_relevance_score: Optional[float] = None  # 0-1

    # Tool and agent metrics
    tool_success_rate: float = 0.0  # 0-1
    a2a_success: Optional[bool] = None  # None if A2A not used in this run
    agents_invoked: list[str] = Field(default_factory=list)
    tool_calls_count: int = 0
    retry_count: int = 0

    # Performance
    latency_ms: float = 0.0
    total_cost_usd: float = 0.0

    # Errors
    error_occurred: bool = False
    error_message: Optional[str] = None

    # Security
    is_security_test: bool = False
    security_passed: Optional[bool] = None  # None if not a security test

    # LLM-as-Judge scores (populated when use_llm_judge=True in harness)
    # Scores are 0-10 (Gemini rates the answer semantically vs reference)
    llm_judge_correctness: Optional[float] = None   # 0-10
    llm_judge_relevance: Optional[float] = None     # 0-10
    llm_judge_completeness: Optional[float] = None  # 0-10
    llm_judge_overall: Optional[float] = None       # 0-10 (main judge score)
    llm_judge_reasoning: Optional[str] = None       # brief explanation
    llm_judge_is_mock: Optional[bool] = None        # True if judge had no API key

    # Metadata
    notes: str = ""
    timestamp: datetime = Field(default_factory=_now)
    model: str = "gemini-1.5-flash"
    config_hash: str = ""  # hash of settings for reproducibility

