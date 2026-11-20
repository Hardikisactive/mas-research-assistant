"""Unit tests for Pydantic schemas."""
import pytest
from datetime import datetime, timezone
from app.schemas.base import (
    VerificationStatus, WorkflowPattern, AgentStatus, TaskType, PersonaType,
    SourceRecord, EvidenceRecord, Finding, DataAnalysisResult,
    CostMetrics, ExecutionSummary, AgentEvent, ToolCall,
)
from app.schemas.outputs import FinalResponse, BlackboardUpdate, AgentMessage
from app.schemas.messages import A2ATaskRequest, A2ATaskResponse, AgentCard
from app.schemas.evaluation import EvaluationRecord


class TestEnums:
    def test_verification_status_values(self):
        assert VerificationStatus.PASS == "PASS"
        assert VerificationStatus.NEEDS_REVISION == "NEEDS_REVISION"
        assert VerificationStatus.INSUFFICIENT_EVIDENCE == "INSUFFICIENT_EVIDENCE"
        assert VerificationStatus.PENDING == "PENDING"

    def test_workflow_pattern_values(self):
        for p in ["HIERARCHICAL", "PARALLEL", "SEQUENTIAL", "BASELINE"]:
            assert WorkflowPattern(p).value == p

    def test_persona_type_values(self):
        for p in ["STUDENT", "RESEARCHER", "FACULTY_EVALUATOR", "DATA_ANALYST", "ADVERSARIAL"]:
            assert PersonaType(p).value == p


class TestSourceRecord:
    def test_defaults(self):
        s = SourceRecord()
        assert s.source_id  # auto-generated UUID
        assert s.title == ""
        assert s.url == ""
        assert s.credibility_score is None

    def test_with_data(self):
        s = SourceRecord(title="Test", url="https://example.com", snippet="excerpt")
        assert s.title == "Test"
        assert s.url == "https://example.com"


class TestEvidenceRecord:
    def test_defaults(self):
        e = EvidenceRecord()
        assert e.evidence_id
        assert e.relevance_score == 0.0
        assert e.page_number is None

    def test_relevance_score(self):
        e = EvidenceRecord(relevance_score=0.95)
        assert e.relevance_score == 0.95


class TestFinding:
    def test_required_claim(self):
        f = Finding(claim="The sky is blue")
        assert f.claim == "The sky is blue"
        assert f.verification_status == VerificationStatus.PENDING

    def test_with_evidence(self):
        f = Finding(
            claim="Claim",
            evidence_ids=["ev-001", "ev-002"],
            verification_status=VerificationStatus.PASS,
            confidence=0.9,
        )
        assert len(f.evidence_ids) == 2
        assert f.confidence == 0.9


class TestExecutionSummary:
    def test_total_cost(self):
        summary = ExecutionSummary(
            cost_metrics=[
                CostMetrics(estimated_cost_usd=0.001, agent_name="a"),
                CostMetrics(estimated_cost_usd=0.002, agent_name="b"),
            ]
        )
        assert abs(summary.total_estimated_cost_usd - 0.003) < 1e-9


class TestFinalResponse:
    def test_minimal(self):
        resp = FinalResponse(query="Test", answer="Answer")
        assert resp.run_id  # auto UUID
        assert resp.is_mock is False
        assert resp.workflow_pattern == WorkflowPattern.HIERARCHICAL

    def test_to_markdown(self):
        resp = FinalResponse(
            query="Q",
            answer="The answer is 42.",
            sources=[SourceRecord(title="Wiki", url="https://en.wikipedia.org")],
        )
        md = resp.to_markdown()
        assert "The answer is 42." in md
        assert "Wikipedia" in md or "Wiki" in md

    def test_mock_flag(self):
        resp = FinalResponse(query="Q", answer="stub", is_mock=True)
        md = resp.to_markdown()
        assert "Mock mode" in md or "mock" in md.lower()

    def test_model_dump_roundtrip(self):
        resp = FinalResponse(query="Q", answer="A")
        data = resp.model_dump(mode="json")
        resp2 = FinalResponse(**data)
        assert resp.run_id == resp2.run_id


class TestA2ASchemas:
    def test_task_request(self):
        req = A2ATaskRequest(
            requesting_agent="crewai",
            task_type="rag_query",
            payload={"query": "Test"},
        )
        assert req.task_id
        assert req.timeout_seconds == 60

    def test_task_response(self):
        resp = A2ATaskResponse(
            task_id="abc",
            responding_agent="adk-rag",
            status="success",
            result={"answer": "Found it"},
            duration_ms=123.4,
        )
        assert resp.status == "success"
        assert resp.error_message is None

    def test_agent_card(self):
        card = AgentCard(
            name="RAG Agent",
            framework="google-adk",
            capabilities=["rag_query"],
            endpoint="http://localhost:8001/a2a/task",
        )
        assert card.version == "1.0"


class TestEvaluationRecord:
    def test_defaults(self):
        rec = EvaluationRecord()
        assert rec.eval_id
        assert rec.task_completed is False
        assert rec.error_occurred is False
        assert rec.is_security_test is False

    def test_with_data(self):
        rec = EvaluationRecord(
            test_case_id="F001",
            query="Speed of light?",
            actual_answer="299,792,458 m/s",
            task_completed=True,
            correctness_score=1.0,
            latency_ms=1234.5,
        )
        assert rec.correctness_score == 1.0
        assert rec.latency_ms == 1234.5

