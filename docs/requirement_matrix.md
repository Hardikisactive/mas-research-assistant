# Faculty Requirements Matrix

This document maps each of the 11 mandatory faculty requirements to specific implementation files, tests, and evidence.

---

## Requirement Compliance Table

| # | Requirement | Status | Implementation Files | Tests |
|---|------------|--------|---------------------|-------|
| 1 | Blackboard architecture | ✅ Done | `app/state/blackboard.py` | `tests/unit/test_blackboard.py` (20 tests) |
| 2 | ≥2 external MCP tools | ✅ Done (4 tools) | `app/tools/mcp/server.py` | `tests/unit/test_mcp_tools.py` (17 tests) |
| 3 | Pydantic-validated structured output | ✅ Done | `app/schemas/` (4 files) | `tests/unit/test_schemas.py` (19 tests) |
| 4 | Agentic patterns (hierarchical, parallel, sequential) | ✅ Done | `app/workflows/` (4 files) | `tests/e2e/test_workflows.py` (9 tests) |
| 5 | Monitoring callbacks / observability | ✅ Done | `app/observability/` (3 files) | Covered in e2e tests + Streamlit dashboard |
| 6 | A2A cross-framework communication | ✅ Done | `app/protocols/a2a/` (4 files) | `tests/integration/test_a2a.py` (5 tests) |
| 7 | CrewAI + Google ADK (no LangChain) | ✅ Done | `app/agents/` (6 agents) | All test suites |
| 8 | Guardrails (injection, file, output, tool) | ✅ Done | `app/security/` (2 files) | `tests/unit/test_guardrails.py` (37), `tests/security/` (26) |
| 9 | Traceability / observability / audit logs | ✅ Done | `app/observability/`, `app/state/blackboard.py` | `tests/unit/test_blackboard.py` |
| 10 | 40+ evaluation runs with charts | ✅ Ready | `app/evaluation/`, `evaluation_data/` | Harness CLI |
| 11 | Cloud deployment | ✅ Ready | `Dockerfile`, `deployment/` | `docs/deployment.md` |

**Total tests: 146 passing, 0 failures** (as of October 2026)

---

## Detailed Evidence

### Requirement 1 — Blackboard Architecture

> *Shared context, intermediate results, and state updates between agents.*

**Evidence:**
- `app/state/blackboard.py` — SQLite-backed shared state with WAL mode
- Every agent reads from and writes to the same `run_id` row
- Fields: `research_results`, `rag_results`, `data_analysis_results`, `verification_results`, `final_answer`, `sources`, `errors`, `events`, `tool_calls`
- Thread-safe locking for parallel workflows
- Audit log records every field change with `changed_by`, timestamp, old/new values

**Test:**
```powershell
python -m pytest tests/unit/test_blackboard.py -v
# 20 tests: create, update, concurrent access, agent visibility, audit log
```

---

### Requirement 2 — MCP Tools

> *At least two genuinely usable external tools exposed through MCP.*

**Evidence:**
- `app/tools/mcp/server.py` — FastMCP server exposing **4 tools**:
  1. `web_search` — DuckDuckGo real-time search
  2. `document_retrieval` — FAISS semantic search over uploaded documents
  3. `calculator` — Safe arithmetic evaluation
  4. `data_profiler` — pandas CSV profiling

Start server: `python -m app.tools.mcp.server`

**Test:**
```powershell
python -m pytest tests/unit/test_mcp_tools.py -v
# 17 tests covering all 4 tools
```

---

### Requirement 3 — Pydantic Structured Output

> *Pydantic-validated structured final output, rendered as Markdown, tables, or JSON.*

**Evidence:**
- `app/schemas/base.py` — Enums, SourceRecord, EvidenceRecord, Finding, DataAnalysisResult, ExecutionSummary
- `app/schemas/outputs.py` — `FinalResponse` (main output), `BlackboardUpdate`, `AgentMessage`
- `app/schemas/messages.py` — `A2ATaskRequest`, `A2ATaskResponse`, `AgentCard`
- `app/schemas/evaluation.py` — `EvaluationRecord` (40+ fields)
- `FinalResponse.to_markdown()` renders output as formatted Markdown

**Test:**
```powershell
python -m pytest tests/unit/test_schemas.py -v
# 19 tests: schema validation, defaults, round-trip serialisation, Markdown rendering
```

---

### Requirement 4 — Agentic Patterns

> *Hierarchical, parallel, and sequential workflows.*

**Evidence:**
- `app/workflows/hierarchical.py` — Supervisor → Research → RAG(A2A) → DataAnalysis → Synthesis → Critic
- `app/workflows/parallel.py` — Research ‖ RAG in threads → Synthesis → Critic
- `app/workflows/sequential.py` — RAG → Critic verify → Synthesis (strict order)
- `app/workflows/baseline.py` — Single LLM (comparison baseline)
- `app/workflows/engine.py` — Routes to the correct pattern

**Test:**
```powershell
python -m pytest tests/e2e/test_workflows.py -v
# 9 tests: all 4 patterns run, guardrail rejection, blackboard populated
```

---

### Requirement 5 — Monitoring Callbacks

> *Agent events, intermediate outputs, execution flow, timing, and errors.*

**Evidence:**
- `app/observability/logger.py` — StructuredFormatter (JSON logs), per-agent loggers
- `app/observability/metrics.py` — MetricsCollector (tokens, latency, tool calls, A2A)
- `app/observability/tracer.py` — Span-based tracer with parent-child relationships
- Blackboard `record_event()` — every agent start/complete/fail is recorded
- Streamlit Dashboard (`app/ui/pages/dashboard.py`) — live metrics display
- Streamlit Workflow Inspector — per-run event timeline

---

### Requirement 6 — A2A Cross-Framework Communication

> *A2A protocol with cross-framework interoperability.*

**Evidence:**
- `app/protocols/a2a/server.py` — FastAPI server wrapping ADK RAG agent
  - `GET /health` — liveness check
  - `GET /.well-known/agent.json` — capability/discovery metadata
  - `POST /a2a/task` — structured task submission
- `app/protocols/a2a/client.py` — `A2AClient` (HTTP client with timeout, error handling) + `A2ARagTool` (CrewAI tool)
- `app/schemas/messages.py` — `A2ATaskRequest`, `A2ATaskResponse`, `AgentCard` schemas
- Request IDs, timeouts (30s), error responses, status codes all implemented

**Demonstrated:** In HIERARCHICAL workflow, CrewAI's `A2ARagTool` sends an HTTP POST to the ADK FastAPI server, which runs the `LlmAgent`, and returns a structured JSON response. This is real HTTP communication between two different framework processes.

**Test:**
```powershell
# Offline tests (always pass):
python -m pytest tests/integration/test_a2a.py -v

# Live integration test (requires A2A server running):
python -m app.protocols.a2a.server   # terminal 1
python -m pytest tests/integration/test_a2a.py -v -m integration   # terminal 2
```

---

### Requirement 7 — CrewAI + Google ADK

> *Use BOTH CrewAI and Google ADK. No LangChain, AutoGen, LangGraph, Semantic Kernel.*

**Evidence:**
- **CrewAI agents** (5): Supervisor, Research, DataAnalysis, Critic, Synthesis (`app/agents/`)
- **Google ADK agent** (1): RAG Agent using `google.adk.agents.LlmAgent` (`app/agents/rag/adk_agent.py`)
- No LangChain, AutoGen, LangGraph, or Semantic Kernel imports anywhere in the codebase

```python
# CrewAI (supervisor example)
from crewai import Agent, Task, Crew

# Google ADK (RAG agent)
from google.adk.agents import LlmAgent
agent = LlmAgent(name="rag_agent", model="gemini-3.1-flash-lite", tools=[...])
```

---

### Requirement 8 — Guardrails

> *Input validation, prompt injection, unsafe tool use, malformed tool output, untrusted retrieved content.*

**Evidence:**
- `app/security/guardrails.py`: `validate_query()`, `validate_file_upload()`, `validate_retrieved_content()`, `validate_tool_output()`, `validate_url()`, `GuardrailViolation`
- `app/security/validators.py`: `validate_csv_path()`, `validate_expression()`, `sanitize_html()`
- Injection blocklist with 10+ patterns
- DataAnalysis tool uses allowlisted operations only — no `eval()`, no shell

**Test:**
```powershell
python -m pytest tests/unit/test_guardrails.py tests/security/test_injection.py -v
# 63 tests total
```

---

### Requirement 9 — Traceability and Audit Logs

> *Observability, audit logs, and provenance.*

**Evidence:**
- `app/state/blackboard.py` — immutable `audit_log` table: field, old_value, new_value, changed_by, timestamp
- `app/observability/tracer.py` — span-based pipeline tracing
- `app/observability/logger.py` — structured JSON logs with run_id, agent_name, duration_ms
- Every tool call logged to `tool_calls` table with input/output summary
- Agent events logged to `events` table with status and duration
- Streamlit Workflow Inspector shows full audit trail for any run

**Test:**
```powershell
python -m pytest tests/unit/test_blackboard.py::TestBlackboardListRuns::test_audit_log_populated -v
```

---

### Requirement 10 — Evaluation Runs (≥40)

> *End-to-end evaluation across ≥40 runs, costs, latency, boxplots, heatmaps.*

**Evidence:**
- `evaluation_data/test_cases/all_cases.json` — 50 test cases (9 categories)
- `app/evaluation/harness.py` — full CLI harness, saves JSON + CSV
- `app/evaluation/charts.py` — generates boxplots, heatmaps, bar charts

**Run:**
```powershell
python -m app.evaluation.harness --patterns BASELINE HIERARCHICAL --limit 25
# Generates 50 runs, saves to evaluation_data/results/
```

**Charts generated:**
- `evaluation_data/results/charts/latency_boxplot.png`
- `evaluation_data/results/charts/agent_heatmap.png`
- `evaluation_data/results/charts/completion_bar.png`

---

### Requirement 11 — Cloud Deployment

> *Deploy on a cloud platform with documented steps.*

**Evidence:**
- `Dockerfile` — Python 3.12-slim, non-root user, FAISS support, healthcheck
- `.dockerignore` — excludes `.env`, `data/`, `__pycache__`
- `deployment/cloud_run_deploy.sh` — full automated deploy script
- `deployment/README.md` — step-by-step manual deploy guide
- Target platform: **Google Cloud Run** (serverless containers)
- Secrets via **Google Secret Manager** (API key never in container image)

**Deploy:**
```bash
export GCP_PROJECT_ID=your-project-id
export GOOGLE_API_KEY=your-key
chmod +x deployment/cloud_run_deploy.sh
./deployment/cloud_run_deploy.sh
```

---

## Test Summary

```
tests/e2e/test_workflows.py          9 tests  ✅
tests/integration/test_a2a.py        5 tests  ✅
tests/security/test_injection.py    26 tests  ✅
tests/unit/test_blackboard.py       20 tests  ✅
tests/unit/test_guardrails.py       37 tests  ✅
tests/unit/test_mcp_tools.py        17 tests  ✅
tests/unit/test_rag.py              13 tests  ✅
tests/unit/test_schemas.py          19 tests  ✅
─────────────────────────────────────────────
TOTAL                              146 tests  ✅  0 failures
```

Run all:
```powershell
cd e:\PRJ-4\mas_project
python -m pytest tests/ -m "not integration" -v --tb=short
```

