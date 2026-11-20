# Blackboard Architecture and Agent Messaging

## What is the Blackboard Pattern?

The **Blackboard** is a shared, persistent data store that all agents read from and write to during a workflow run. It acts as the "single source of truth" for the state of any given query-processing pipeline.

Without a blackboard, agents would need to pass data directly to each other (point-to-point coupling). With a blackboard, every agent independently reads what it needs and posts what it produces — decoupling agents from one another completely.

```
Supervisor      Research        RAG (ADK)      Critic      Synthesis
    │               │               │              │            │
    ▼               ▼               ▼              ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    BLACKBOARD (SQLite)                          │
│                                                                 │
│  run_id | query | status | plan | research_results | rag_results│
│  data_analysis_results | verification_results | final_answer    │
│  sources | errors | events | tool_calls | tokens_used           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Implementation

**File:** `app/state/blackboard.py`

**Storage:** SQLite with WAL (Write-Ahead Logging) mode for concurrent read performance.

**Thread safety:** A `threading.Lock` guards every write operation, making the blackboard safe for parallel workflows.

**Singleton:** `get_blackboard()` returns a single shared instance per process.

```python
from app.state.blackboard import get_blackboard

bb = get_blackboard()
```

---

## Full State Schema

Every workflow run creates one row in the `runs` table with these fields:

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | TEXT (UUID) | Unique run identifier |
| `conversation_id` | TEXT | Optional grouping ID across runs |
| `original_query` | TEXT | Raw user query (as submitted) |
| `sanitized_query` | TEXT | After guardrail processing |
| `persona` | TEXT | `RESEARCHER\|STUDENT\|ANALYST\|EXPERT\|GENERAL` |
| `workflow_pattern` | TEXT | `HIERARCHICAL\|PARALLEL\|SEQUENTIAL\|BASELINE` |
| `plan` | TEXT (JSON) | Supervisor-generated task plan |
| `current_status` | TEXT | `PENDING\|RUNNING\|COMPLETED\|FAILED\|REJECTED` |
| `agents_needed` | TEXT (JSON list) | Which agents the Supervisor selected |
| `agent_outputs` | TEXT (JSON dict) | Raw per-agent output strings |
| `research_results` | TEXT (JSON) | Research Agent findings and sources |
| `rag_results` | TEXT (JSON) | RAG Agent retrieved chunks and answer |
| `data_analysis_results` | TEXT (JSON) | Data Analysis results |
| `verification_results` | TEXT (JSON) | Critic verdict and issues |
| `final_answer` | TEXT | Synthesis Agent final response |
| `sources` | TEXT (JSON list) | All source records |
| `errors` | TEXT (JSON list) | Accumulated errors |
| `tokens_used` | TEXT (JSON dict) | Per-agent token counts |
| `cost_estimate_usd` | REAL | Estimated API cost (labelled as estimate) |
| `total_duration_ms` | REAL | End-to-end wall-clock time |
| `version` | INTEGER | Optimistic concurrency version counter |
| `created_at` | TEXT | ISO 8601 timestamp |
| `updated_at` | TEXT | ISO 8601 timestamp of last update |

### Events Table

Every significant agent action records an event:

| Column | Description |
|--------|-------------|
| `run_id` | Foreign key to runs |
| `agent_name` | Which agent fired the event |
| `event_type` | `started\|completed\|failed\|tool_call\|handoff` |
| `status` | Current status at event time |
| `message` | Human-readable description |
| `duration_ms` | How long this step took |
| `timestamp` | ISO 8601 |

### Tool Calls Table

Every MCP or direct tool invocation is logged:

| Column | Description |
|--------|-------------|
| `run_id` | Foreign key |
| `agent_name` | Calling agent |
| `tool_name` | e.g. `web_search`, `document_retrieval` |
| `input_summary` | First 200 chars of input |
| `output_summary` | First 200 chars of output |
| `success` | Boolean |
| `duration_ms` | Execution time |
| `timestamp` | ISO 8601 |

### Audit Log Table

Every state change is immutably recorded:

| Column | Description |
|--------|-------------|
| `run_id` | Foreign key |
| `field_name` | Which field changed |
| `old_value` | Previous value (truncated) |
| `new_value` | New value (truncated) |
| `changed_by` | Which agent/component |
| `timestamp` | ISO 8601 |

---

## State Machine

```
                    ┌─────────┐
                    │ PENDING │  ← run created by engine
                    └────┬────┘
                         │ guardrails pass
                         ▼
                    ┌─────────┐
            ┌──────►│ RUNNING │  ← agents executing
            │       └────┬────┘
            │            │
            │    ┌───────┴────────┐
            │    ▼                ▼
            │ ┌──────────┐  ┌──────────┐
            │ │COMPLETED │  │  FAILED  │
            │ └──────────┘  └──────────┘
            │
       REJECTED (guardrail violation — never reaches RUNNING)
```

---

## Blackboard API

### Create a Run

```python
run_id = bb.create_run(
    query="What is machine learning?",
    persona="RESEARCHER",
    pattern="HIERARCHICAL",
    conversation_id=None,  # optional
)
# Returns: UUID string
```

### Read a Run

```python
run = bb.get_run(run_id)
# Returns: dict of all fields, or None if not found
print(run["current_status"])      # "RUNNING"
print(run["research_results"])    # JSON dict or {}
```

### Update a Field

```python
bb.update_field(run_id, "current_status", "COMPLETED", changed_by="synthesis_agent")
# Returns: True on success, False if run not found
# Increments version counter
# Records audit entry automatically
```

Allowed fields for update: `current_status`, `plan`, `agents_needed`, `agent_outputs`,
`research_results`, `rag_results`, `data_analysis_results`, `verification_results`,
`final_answer`, `sources`, `tokens_used`, `cost_estimate_usd`, `total_duration_ms`.

### Append to List Fields

```python
bb.append_to_list_field(run_id, "errors", "Timeout in research agent after 30s")
bb.append_to_list_field(run_id, "sources", {"url": "https://...", "title": "..."})
```

### Record an Agent Event

```python
bb.record_event(
    run_id=run_id,
    agent_name="research_agent",
    event_type="completed",
    status="SUCCESS",
    message="Found 5 sources for query",
    duration_ms=3200.0,
)
```

### Record a Tool Call

```python
bb.record_tool_call(
    run_id=run_id,
    agent_name="research_agent",
    tool_name="web_search",
    input_summary="machine learning history",
    output_summary='{"result_count": 5, ...}',
    success=True,
    duration_ms=850.0,
)
```

### Query History

```python
events = bb.get_events(run_id)           # list of event dicts
tools  = bb.get_tool_calls(run_id)       # list of tool call dicts
audit  = bb.get_audit_log(run_id)        # list of field-change records
runs   = bb.list_runs(limit=50)          # recent runs summary
```

---

## Concurrency

The blackboard uses a `threading.RLock` (reentrant lock). All write operations (`create_run`, `update_field`, `append_to_list_field`, `record_event`, `record_tool_call`) acquire the lock before any DB write.

The `PARALLEL` workflow pattern runs Research and RAG agents in separate threads simultaneously. Both write to the same blackboard safely because each writes to a *different field* — no field-level conflict is possible.

**Tested:** `TestBlackboardConcurrency::test_concurrent_updates_are_safe` (20 threads, 100 updates).

---

## A2A Message Flow (CrewAI ↔ ADK)

The A2A protocol is the communication channel between the CrewAI side and the ADK RAG agent. The Blackboard stores the *results* of A2A calls, not the messages themselves.

```
CrewAI Hierarchical Workflow
  │
  ├─1─► Supervisor writes plan → Blackboard
  │
  ├─2─► Research Agent runs → writes research_results → Blackboard
  │
  ├─3─► A2ARagTool._run(query)
  │         │
  │         │  HTTP POST /a2a/task  ← A2A message (JSON)
  │         │  {task_id, task_type: "rag_query", payload: {query, top_k}}
  │         │
  │         ▼
  │     ADK A2A Server (port 8002)
  │         │
  │         │  → run_adk_rag_agent_sync(query)
  │         │  → FAISS search + LlmAgent answer
  │         │
  │         │  HTTP 200 A2ATaskResponse
  │         │  {task_id, status: "COMPLETED", result: {answer, excerpts, ...}}
  │         ▼
  │     CrewAI receives response dict
  │
  ├─4─► writes rag_results → Blackboard
  │
  ├─5─► Critic reads research_results + rag_results → writes verification_results
  │
  └─6─► Synthesis reads all → writes final_answer → FinalResponse returned
```

### A2A Message Schema

**Request** (`POST /a2a/task`):
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_type": "rag_query",
  "payload": { "query": "...", "top_k": 5, "session_id": "optional" },
  "sender_agent": "crewai_research_agent",
  "created_at": "2024-01-01T12:00:00Z"
}
```

**Response**:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "COMPLETED",
  "result": {
    "answer": "Based on the document...",
    "excerpts": ["chunk 1", "chunk 2"],
    "document_ids": ["doc_abc"],
    "scores": [0.87, 0.74],
    "success": true,
    "duration_ms": 312.4
  },
  "error": null,
  "completed_at": "2024-01-01T12:00:01Z"
}
```

---

## SQLite Configuration

```sql
PRAGMA journal_mode=WAL;   -- concurrent readers, one writer
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL; -- balance durability and speed
```

The `data/blackboard.db` file is excluded from git (`.gitignore`). For production (Cloud Run), use PostgreSQL via environment variable override.

