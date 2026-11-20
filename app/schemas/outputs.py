"""
Final output and Blackboard update schemas.
FinalResponse is the Pydantic-validated output produced by the Synthesis Agent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import (
    DataAnalysisResult,
    EvidenceRecord,
    ExecutionSummary,
    Finding,
    SourceRecord,
    VerificationStatus,
    WorkflowPattern,
    _now,
    _uid,
)


class FinalResponse(BaseModel):
    """
    Pydantic-validated final output of a complete workflow run.
    This is the authoritative response returned to the user.
    """
    model_config = ConfigDict(use_enum_values=True)

    run_id: str = Field(default_factory=_uid)
    query: str
    sanitized_query: str = ""
    answer: str
    key_findings: list[Finding] = Field(default_factory=list)
    sources: list[SourceRecord] = Field(default_factory=list)
    document_evidence: list[EvidenceRecord] = Field(default_factory=list)
    data_analysis: Optional[DataAnalysisResult] = None
    verification_status: VerificationStatus = VerificationStatus.PENDING
    limitations: list[str] = Field(default_factory=list)
    agents_used: list[str] = Field(default_factory=list)
    workflow_pattern: WorkflowPattern = WorkflowPattern.HIERARCHICAL
    execution_summary: ExecutionSummary = Field(default_factory=ExecutionSummary)
    created_at: datetime = Field(default_factory=_now)

    # Transparency flags
    is_mock: bool = False        # True when running without real API keys
    has_real_sources: bool = False  # True when sources were genuinely retrieved
    critic_notes: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        """Render the response as a readable Markdown string."""
        parts = [f"# Research Answer\n\n{self.answer}\n"]

        if self.key_findings:
            parts.append("## Key Findings\n")
            for i, f in enumerate(self.key_findings, 1):
                status_icon = {"PASS": "✅", "NEEDS_REVISION": "⚠️",
                               "INSUFFICIENT_EVIDENCE": "❓", "PENDING": "⏳"}.get(
                    str(f.verification_status), "")
                parts.append(f"{i}. {status_icon} {f.claim}")
            parts.append("")

        if self.sources:
            parts.append("## Sources\n")
            for s in self.sources[:10]:
                if s.url:
                    parts.append(f"- [{s.title or s.url}]({s.url})")
                else:
                    parts.append(f"- {s.title or '(no title)'}")
            parts.append("")

        if self.document_evidence:
            parts.append("## Document Evidence\n")
            for e in self.document_evidence[:5]:
                parts.append(f"- **{e.filename}** (chunk {e.chunk_index}, score {e.relevance_score:.2f})")
                parts.append(f"  > {e.text[:200]}...")
            parts.append("")

        if self.limitations:
            parts.append("## Limitations\n")
            for lim in self.limitations:
                parts.append(f"- {lim}")
            parts.append("")

        parts.append(f"---\n*Pattern: {self.workflow_pattern} | "
                     f"Agents: {', '.join(self.agents_used)} | "
                     f"Verification: {self.verification_status}*")

        if self.is_mock:
            parts.append("\n> ⚠️ **Mock mode** — no real LLM calls were made (API key not configured).")

        return "\n".join(parts)


class BlackboardUpdate(BaseModel):
    """Atomic field update recorded in the Blackboard audit log."""
    update_id: str = Field(default_factory=_uid)
    run_id: str
    field_name: str
    value: Any
    updated_by: str
    timestamp: datetime = Field(default_factory=_now)
    version: int = 1


class AgentMessage(BaseModel):
    """Generic inter-agent message (used for A2A transport)."""
    message_id: str = Field(default_factory=_uid)
    from_agent: str
    to_agent: str
    task_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_now)
    correlation_id: str = Field(default_factory=_uid)

