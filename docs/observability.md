# Observability, Logging, and Metrics

## Overview

The system has three observability layers:

| Layer | File | What it captures |
|-------|------|-----------------|
| **Structured Logging** | `app/observability/logger.py` | All agent events, tool calls, errors — JSON format |
| **Metrics Collector** | `app/observability/metrics.py` | Tokens, latency, cost estimates, A2A calls — per run |
| **Tracer** | `app/observability/tracer.py` | Span-based timing for pipeline steps |

Plus the **Blackboard audit log** (in SQLite) as an immutable event history.

---

## 1. Structured Logging

**File:** `app/observability/logger.py`

### Log Format

Every log entry is emitted as a single-line JSON object (in production) or human-readable text (in development). The `LOG_LEVEL` env var controls verbosity.

**JSON log entry example:**
```json
{
  "timestamp": "2024-01-01T12:00:01.234Z",
  "level": "INFO",
  "logger": "mas.research_agent",
  "message": "WebSearch: 'machine learning history' → 5 results in 823ms",
  "run_id": "550e8400-...",
  "agent": "research_agent",
  "tool": "web_search",
  "duration_ms": 823.4
}
```

### Setup

```python
from app.observability.logger import setup_logging, get_agent_logger

# Call once at startup
setup_logging(level="INFO", json_format=True)

# Per-agent loggers
logger = get_agent_logger("research_agent")
logger.info("Search completed", extra={"run_id": run_id, "results": 5})
```

### Log Levels Used

| Level | Used for |
|-------|---------|
| `DEBUG` | Tool input/output details, intermediate reasoning |
| `INFO` | Agent started/completed, tool called, A2A request sent |
| `WARNING` | Guardrail triggered, search returned 0 results, fallback activated |
| `ERROR` | API call failed, agent exception, A2A server unreachable |
| `CRITICAL` | Blackboard corruption, unrecoverable startup failure |

### Secret Redaction

The `StructuredFormatter` automatically redacts values whose keys match:
`api_key`, `secret`, `password`, `token`, `authorization`

These are replaced with `[REDACTED]` in all log output.

---

## 2. Metrics Collector

**File:** `app/observability/metrics.py`

The `MetricsCollector` is a thread-safe singleton that accumulates metrics across all agents in a run.

### Collected Metrics

```python
from app.observability.metrics import get_metrics

metrics = get_metrics()

# Record tokens for a run
metrics.record_tokens(run_id, agent_name="research_agent",
                      input_tokens=250, output_tokens=180)

# Record a tool call
metrics.record_tool_call(run_id, tool_name="web_search",
                         success=True, duration_ms=823.4)

# Record an A2A call
metrics.record_a2a_call(run_id, target_agent="rag_agent",
                        success=True, duration_ms=1240.0)

# Get summary for a run
summary = metrics.get_run_summary(run_id)
```

### Run Summary Fields

| Field | Description |
|-------|-------------|
| `total_input_tokens` | Sum of all agents' input tokens |
| `total_output_tokens` | Sum of all agents' output tokens |
| `cost_estimate_usd` | Estimated API cost (labelled as estimate, not billing) |
| `total_latency_ms` | End-to-end wall-clock time |
| `agent_latencies_ms` | Per-agent timing dict |
| `tool_call_count` | Total tool invocations |
| `tool_success_rate` | Fraction of successful tool calls |
| `a2a_call_count` | Cross-framework A2A calls made |
| `a2a_success_rate` | Fraction successful |
| `agent_count` | Number of agents that ran |

> [!NOTE]
> Token counts and cost estimates are **heuristics** based on approximate counting and published pricing.
> They should be labelled as estimates in all reports. Actual API billing may differ.

### Cost Estimation

```python
from app.config.pricing import estimate_cost

cost = estimate_cost(
    input_tokens=1500,
    output_tokens=800,
    model="gemini-3.1-flash-lite"
)
# Returns: {"cost_usd": 0.000354, "label": "estimate — not actual billing"}
```

---

## 3. Tracer (Span-based)

**File:** `app/observability/tracer.py`

A lightweight in-process tracer records spans with parent-child relationships, timing, and error status.

```python
from app.observability.tracer import Tracer

tracer = Tracer()  # creates a new trace_id

with tracer.span("supervisor.classify") as span:
    span.attributes["query_len"] = len(query)
    result = classify_query(query)

with tracer.span("research.web_search") as span:
    results = search(query)
    span.attributes["result_count"] = len(results)

# Get the full trace
trace = tracer.get_trace()
# [{"name": "supervisor.classify", "duration_ms": 12.3, ...}, ...]

summary = tracer.summary()
# {"trace_id": "abc123", "span_count": 5, "total_duration_ms": 4821.0, "errors": []}
```

### OpenTelemetry Integration (Optional)

When `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT` is set, spans are also exported to any OTLP-compatible backend (Jaeger, Zipkin, Google Cloud Trace, etc.).

```bash
# Enable in .env:
OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

---

## 4. Blackboard Audit Log

Every field change in the Blackboard is recorded immutably in the `audit_log` SQLite table. This provides:
- Full provenance: which agent changed what and when
- Replay capability: reconstruct state at any point in time
- Compliance evidence: tamper-evident record of all decisions

```python
audit = bb.get_audit_log(run_id)
# [
#   {"field": "current_status", "old": "PENDING", "new": "RUNNING",
#    "changed_by": "engine", "timestamp": "2024-01-01T12:00:00Z"},
#   {"field": "research_results", "old": "{}", "new": "{...}",
#    "changed_by": "research_agent", "timestamp": "..."},
#   ...
# ]
```

---

## 5. Streamlit Dashboard

The `Dashboard` page (`app/ui/pages/dashboard.py`) shows:

- **Live session metrics** — current run count, token total, cost estimate
- **Latency boxplots** — per workflow pattern (from evaluation results)
- **Agent heatmaps** — which agents ran for which query types
- **Completion rate bar chart** — pass/fail by pattern
- **Per-run table** — sortable list of recent runs with status

The **Workflow Inspector** page (`app/ui/pages/workflow_inspector.py`) shows:
- Full Blackboard state for any run
- Agent events timeline
- Tool call log
- Audit trail

---

## 6. Evaluation Metrics

The evaluation harness (`app/evaluation/harness.py`) records:

| Metric | Type | Description |
|--------|------|-------------|
| `correctness_score` | 0.0–1.0 | Keyword overlap with reference answer (heuristic) |
| `groundedness_score` | 0.0–1.0 | Citation and source presence (heuristic) |
| `latency_ms` | float | End-to-end wall-clock time |
| `total_tokens` | int | Input + output token estimate |
| `cost_estimate_usd` | float | Estimated API cost |
| `completion_success` | bool | Did the workflow complete without error? |
| `is_mock` | bool | Was a real LLM used? |
| `verification_status` | enum | PASS / NEEDS_REVISION / INSUFFICIENT_EVIDENCE |

> [!IMPORTANT]
> `correctness_score` and `groundedness_score` are **keyword-matching heuristics**.
> They are NOT validated hallucination metrics or human evaluation scores.
> They should be labelled as heuristic estimates in all reports and presentations.

---

## Viewing Logs

```powershell
# Real-time log tail while running
cd e:\PRJ-4\mas_project
python -m pytest tests/e2e/ -v -s 2>&1 | Select-String "INFO|WARNING|ERROR"

# Or run the app and watch Streamlit's built-in log display
streamlit run app/ui/app.py
# → Settings page shows log output
# → Workflow Inspector shows per-run event timeline
```

