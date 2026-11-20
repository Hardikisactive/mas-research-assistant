"""
Unit tests for MCP tool logic (functions tested directly, not via MCP protocol).
"""
import json
import pytest


# ---------------------------------------------------------------------------
# Calculator tool
# ---------------------------------------------------------------------------

from app.tools.mcp.server import calculator


class TestCalculator:
    def test_addition(self):
        result = json.loads(calculator("2 + 2"))
        assert result["result"] == 4

    def test_subtraction(self):
        result = json.loads(calculator("10 - 3"))
        assert result["result"] == 7

    def test_division(self):
        result = json.loads(calculator("10 / 4"))
        assert result["result"] == pytest.approx(2.5)

    def test_sqrt_via_math(self):
        result = json.loads(calculator("math.sqrt(16)"))
        assert result["result"] == pytest.approx(4.0)

    def test_complex_expression(self):
        result = json.loads(calculator("round(math.pi, 4)"))
        assert result["result"] == pytest.approx(3.1416)

    def test_injection_import_rejected(self):
        """__import__('os').system('dir') must not execute; eval should fail."""
        result = json.loads(calculator("__import__('os').system('dir')"))
        assert "error" in result  # NameError because __builtins__ is {}

    def test_injection_exec_rejected(self):
        result = json.loads(calculator("exec('import os')"))
        assert "error" in result

    def test_expression_too_long(self):
        result = json.loads(calculator("1 + " * 60 + "1"))
        assert "error" in result

    def test_division_by_zero(self):
        result = json.loads(calculator("1 / 0"))
        assert "error" in result

    def test_syntax_error(self):
        result = json.loads(calculator("2 +++"))
        assert "error" in result


# ---------------------------------------------------------------------------
# Data profiler — path traversal rejection
# ---------------------------------------------------------------------------

from app.tools.mcp.server import data_profiler


class TestDataProfiler:
    def test_path_traversal_rejected(self):
        result = json.loads(data_profiler("../../etc/passwd"))
        assert "error" in result
        assert result.get("tool_available") is False

    def test_absolute_path_rejected(self):
        result = json.loads(data_profiler("/etc/passwd"))
        assert "error" in result

    def test_missing_file_returns_error(self):
        result = json.loads(data_profiler("nonexistent_file.csv"))
        assert "error" in result


# ---------------------------------------------------------------------------
# Query validation (via guardrails, exercised through the security layer)
# ---------------------------------------------------------------------------

from app.security.guardrails import GuardrailViolation, validate_query


class TestQueryValidation:
    def test_empty_query_rejected(self):
        with pytest.raises(GuardrailViolation) as exc:
            validate_query("")
        assert exc.value.violation_type == "EMPTY_INPUT"

    def test_whitespace_only_rejected(self):
        with pytest.raises(GuardrailViolation) as exc:
            validate_query("     ")
        assert exc.value.violation_type == "EMPTY_INPUT"

    def test_too_long_query_rejected(self):
        with pytest.raises(GuardrailViolation) as exc:
            validate_query("q" * 2001, max_length=2000)
        assert exc.value.violation_type == "INPUT_TOO_LONG"

    def test_valid_query_passes(self):
        result, _ = validate_query("Explain transformer models")
        assert result == "Explain transformer models"

