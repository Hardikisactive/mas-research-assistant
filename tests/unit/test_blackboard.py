"""Unit tests for the SQLite Blackboard."""
import threading
import time
import pytest
from app.state.blackboard import Blackboard


@pytest.fixture
def bb():
    return Blackboard(":memory:")


class TestBlackboardCreate:
    def test_create_run_returns_uuid(self, bb):
        run_id = bb.create_run("What is AI?", "RESEARCHER", "HIERARCHICAL")
        assert run_id
        assert len(run_id) == 36  # UUID4 format

    def test_create_multiple_runs(self, bb):
        r1 = bb.create_run("Q1", "RESEARCHER")
        r2 = bb.create_run("Q2", "STUDENT")
        assert r1 != r2

    def test_get_run_returns_correct_data(self, bb):
        run_id = bb.create_run("Test query", "FACULTY_EVALUATOR", "PARALLEL")
        run = bb.get_run(run_id)
        assert run is not None
        assert run["run_id"] == run_id
        assert run["original_query"] == "Test query"
        assert run["persona"] == "FACULTY_EVALUATOR"
        assert run["workflow_pattern"] == "PARALLEL"
        assert run["current_status"] == "PENDING"
        assert run["version"] == 1

    def test_get_nonexistent_run_returns_none(self, bb):
        assert bb.get_run("nonexistent-uuid") is None


class TestBlackboardUpdateField:
    def test_update_status(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        result = bb.update_field(run_id, "current_status", "RUNNING", "supervisor")
        assert result is True
        run = bb.get_run(run_id)
        assert run["current_status"] == "RUNNING"

    def test_update_increments_version(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        assert bb.get_run(run_id)["version"] == 1
        bb.update_field(run_id, "current_status", "RUNNING", "supervisor")
        assert bb.get_run(run_id)["version"] == 2
        bb.update_field(run_id, "current_status", "COMPLETED", "supervisor")
        assert bb.get_run(run_id)["version"] == 3

    def test_update_dict_field(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        bb.update_field(run_id, "plan", {"agents": ["research", "synthesis"]}, "supervisor")
        run = bb.get_run(run_id)
        assert run["plan"]["agents"] == ["research", "synthesis"]

    def test_update_rejects_unknown_field(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        result = bb.update_field(run_id, "malicious_field", "value", "attacker")
        assert result is False

    def test_update_nonexistent_run_returns_false(self, bb):
        result = bb.update_field("nonexistent", "current_status", "RUNNING", "supervisor")
        assert result is False


class TestBlackboardListFields:
    def test_append_to_errors(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        bb.append_to_list_field(run_id, "errors", "Something went wrong", "agent")
        run = bb.get_run(run_id)
        assert "Something went wrong" in run["errors"]

    def test_append_multiple_items(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        bb.append_to_list_field(run_id, "errors", "error1", "agent")
        bb.append_to_list_field(run_id, "errors", "error2", "agent")
        run = bb.get_run(run_id)
        assert len(run["errors"]) == 2

    def test_append_to_invalid_field_fails(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        result = bb.append_to_list_field(run_id, "plan", "item", "agent")
        assert result is False  # plan is a dict field, not list

    def test_update_dict_subkey(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        bb.update_dict_field(run_id, "agent_outputs", "research", "found 5 sources", "research_agent")
        run = bb.get_run(run_id)
        assert run["agent_outputs"]["research"] == "found 5 sources"


class TestBlackboardEvents:
    def test_record_event(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        event_id = bb.record_event(
            run_id, "research_agent", "started", "RUNNING", "Starting web search"
        )
        assert event_id
        events = bb.get_events(run_id)
        assert len(events) == 1
        assert events[0]["agent_name"] == "research_agent"
        assert events[0]["event_type"] == "started"

    def test_record_tool_call(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        tc_id = bb.record_tool_call(
            run_id, "web_search", "research_agent",
            "query=AI news", "5 results found", True, 234.5
        )
        assert tc_id
        tools = bb.get_tool_calls(run_id)
        assert len(tools) == 1
        assert tools[0]["tool_name"] == "web_search"
        assert tools[0]["success"] == 1


class TestBlackboardConcurrency:
    def test_concurrent_updates_are_safe(self, bb):
        """Multiple threads updating different fields should not corrupt state."""
        run_id = bb.create_run("Concurrent test", "RESEARCHER")
        errors = []

        def update_errors(i):
            try:
                bb.append_to_list_field(run_id, "errors", f"error_{i}", f"agent_{i}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=update_errors, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        run = bb.get_run(run_id)
        assert len(errors) == 0, f"Concurrent errors: {errors}"
        assert len(run["errors"]) == 10

    def test_downstream_agent_sees_upstream_output(self, bb):
        """Prove: upstream agent writes → downstream agent reads correctly."""
        run_id = bb.create_run("Pipeline test", "RESEARCHER")

        # Upstream: research agent writes its output
        bb.update_dict_field(
            run_id, "agent_outputs", "research",
            "Found 5 sources about quantum computing", "research_agent"
        )
        bb.update_field(run_id, "current_status", "RESEARCH_DONE", "research_agent")

        # Downstream: synthesis agent reads research output
        state = bb.get_run(run_id)
        research_output = state["agent_outputs"].get("research", "")
        assert "quantum computing" in research_output
        assert state["current_status"] == "RESEARCH_DONE"


class TestBlackboardListRuns:
    def test_list_runs(self, bb):
        for i in range(3):
            bb.create_run(f"Query {i}", "RESEARCHER")
        runs = bb.list_runs()
        assert len(runs) == 3

    def test_list_runs_limit(self, bb):
        for i in range(10):
            bb.create_run(f"Q{i}", "STUDENT")
        runs = bb.list_runs(limit=5)
        assert len(runs) == 5

    def test_audit_log_populated(self, bb):
        run_id = bb.create_run("Q", "RESEARCHER")
        bb.update_field(run_id, "current_status", "RUNNING", "supervisor")
        audit = bb.get_audit_log(run_id)
        assert len(audit) >= 2  # create_run + update_field

