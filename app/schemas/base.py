"""
Core Pydantic schemas for the Multi-Agent Research Assistant.
All inter-agent messages, tool results, and outputs are validated via these models.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return str(uuid.uuid4())


# ─── Enumerations ──────────────────────────────────────────────────────────────

class VerificationStatus(str, Enum):
    PASS = "PASS"
    NEEDS_REVISION = "NEEDS_REVISION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    PENDING = "PENDING"


class WorkflowPattern(str, Enum):
    HIERARCHICAL = "HIERARCHICAL"
    PARALLEL = "PARALLEL"
    SEQUENTIAL = "SEQUENTIAL"
    BASELINE = "BASELINE"  # single-LLM baseline


class AgentStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TaskType(str, Enum):
    RESEARCH = "RESEARCH"
    DOCUMENT_QA = "DOCUMENT_QA"
    DATA_ANALYSIS = "DATA_ANALYSIS"
    MULTI_AGENT = "MULTI_AGENT"
    FACTUAL = "FACTUAL"
    SECURITY_TEST = "SECURITY_TEST"


class PersonaType(str, Enum):
    STUDENT = "STUDENT"
    RESEARCHER = "RESEARCHER"
    FACULTY_EVALUATOR = "FACULTY_EVALUATOR"
    DATA_ANALYST = "DATA_ANALYST"
    ADVERSARIAL = "ADVERSARIAL"


# ─── Core Data Structures ──────────────────────────────────────────────────────

class SourceRecord(BaseModel):
    """A source of external information retrieved by the Research Agent."""
    model_config = ConfigDict(use_enum_values=True)

    source_id: str = Field(default_factory=_uid)
    title: str = ""
    url: str = ""
    snippet: str = ""
    timestamp: Optional[str] = None
    credibility_score: Optional[float] = None  # 0-1, None if unassessed
    source_type: str = "web"  # "web" | "document" | "api"


class EvidenceRecord(BaseModel):
    """A retrieved chunk from the RAG pipeline."""
    model_config = ConfigDict(use_enum_values=True)

    evidence_id: str = Field(default_factory=_uid)
    document_id: str = ""
    chunk_id: str = ""
    text: str = ""
    relevance_score: float = 0.0
    page_number: Optional[int] = None
    filename: str = ""
    chunk_index: int = 0


class Finding(BaseModel):
    """A single key finding from the research, with evidence and verification."""
    model_config = ConfigDict(use_enum_values=True)

    finding_id: str = Field(default_factory=_uid)
    claim: str
    evidence_ids: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.PENDING
    confidence: Optional[float] = None  # 0-1, None if unassessed


class DataAnalysisResult(BaseModel):
    """Structured result from the Data Analysis Agent."""
    summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    transformations: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    chart_data: Optional[dict] = None
    dataset_shape: Optional[list[int]] = None  # [rows, cols]
    column_names: Optional[list[str]] = None


class CostMetrics(BaseModel):
    """Token usage and cost estimates for one agent invocation."""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    is_estimate: bool = True
    agent_name: str = ""


class ExecutionSummary(BaseModel):
    """Aggregate metrics for one complete workflow run."""
    total_duration_ms: float = 0.0
    agent_count: int = 0
    tool_call_count: int = 0
    retry_count: int = 0
    a2a_calls: int = 0
    cost_metrics: list[CostMetrics] = Field(default_factory=list)

    @property
    def total_estimated_cost_usd(self) -> float:
        return sum(c.estimated_cost_usd for c in self.cost_metrics)


class AgentEvent(BaseModel):
    """A single agent lifecycle event, recorded in the Blackboard."""
    model_config = ConfigDict(use_enum_values=True)

    event_id: str = Field(default_factory=_uid)
    run_id: str = ""
    agent_name: str = ""
    event_type: str = ""  # "started" | "completed" | "failed" | "tool_call" etc.
    timestamp: datetime = Field(default_factory=_now)
    duration_ms: Optional[float] = None
    status: AgentStatus = AgentStatus.PENDING
    summary: str = ""
    error: Optional[str] = None


class ToolCall(BaseModel):
    """Record of a single MCP tool invocation."""
    tool_call_id: str = Field(default_factory=_uid)
    tool_name: str = ""
    agent_name: str = ""
    input_summary: str = ""
    output_summary: Optional[str] = None
    success: bool = True
    duration_ms: float = 0.0
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=_now)

