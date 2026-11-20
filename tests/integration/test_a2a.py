"""Integration tests for A2A protocol client/server interaction.
These tests use a live server if available, otherwise validate the client's
error-handling path when the server is offline.
"""
import json
import pytest
from app.protocols.a2a.client import A2AClient, A2ARagTool
from app.schemas.messages import A2ATaskResponse


class TestA2AClientOffline:
    """Tests that run even when the ADK A2A server is not running."""

    def test_health_check_returns_dict(self):
        client = A2AClient()
        health = client.check_health()
        assert isinstance(health, dict)
        # Server may or may not be running — either way returns a dict
        assert "reachable" in health

    def test_send_task_to_offline_server_returns_error_response(self):
        """Client must gracefully handle a server that is not running."""
        client = A2AClient(base_url="http://localhost:19999")  # No server here
        response = client.send_task(
            task_type="rag_query",
            payload={"query": "test"},
        )
        assert isinstance(response, A2ATaskResponse)
        assert response.status in ("error", "timeout")
        assert response.error_message is not None

    def test_a2a_rag_tool_fallback(self):
        """A2ARagTool must return a usable string when server offline."""
        tool = A2ARagTool()
        result = tool._run("What is quantum computing?")
        data = json.loads(result)
        # Should either have success:True from local fallback or error from offline server
        assert "success" in data or "error" in data
        assert isinstance(result, str)


class TestA2ATaskRequest:
    def test_task_request_schema(self):
        from app.schemas.messages import A2ATaskRequest
        req = A2ATaskRequest(
            requesting_agent="test_agent",
            task_type="rag_query",
            payload={"query": "hello"},
        )
        assert req.task_id  # auto-generated
        dumped = req.model_dump(mode="json")
        assert dumped["task_type"] == "rag_query"

    def test_task_response_schema(self):
        resp = A2ATaskResponse(
            task_id="abc123",
            responding_agent="adk-rag",
            status="success",
            result={"answer": "42"},
            duration_ms=500.0,
        )
        assert resp.status == "success"
        assert resp.result["answer"] == "42"
        assert resp.error_message is None


@pytest.mark.integration
class TestA2AIntegrationLive:
    """
    Live integration tests — only run when ADK A2A server is running.
    Marked with @pytest.mark.integration so they can be skipped:
        pytest -m "not integration"
    """

    def test_health_endpoint(self):
        client = A2AClient()
        health = client.check_health()
        if not health.get("reachable"):
            pytest.skip("ADK A2A server not running — skipping live test")
        assert health.get("agent") == "adk-rag-agent"

    def test_rag_query_round_trip(self):
        """Send a RAG query via A2A and verify the response structure."""
        client = A2AClient()
        health = client.check_health()
        if not health.get("reachable"):
            pytest.skip("ADK A2A server not running")

        response = client.send_task(
            task_type="rag_query",
            payload={"query": "What documents are indexed?"},
            requesting_agent="integration_test",
        )
        assert response.status in ("success", "error")
        assert response.task_id
        assert response.duration_ms >= 0

    def test_agent_card_endpoint(self):
        client = A2AClient()
        health = client.check_health()
        if not health.get("reachable"):
            pytest.skip("ADK A2A server not running")
        card = client.get_agent_card()
        assert "name" in card
        assert card.get("framework") == "google-adk"

