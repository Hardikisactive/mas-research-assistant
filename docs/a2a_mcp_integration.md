# A2A and MCP Integration Guide

## Overview

The system uses two inter-process communication protocols:

| Protocol | Purpose | Port | File |
|----------|---------|------|------|
| **A2A** (Agent-to-Agent) | Cross-framework: CrewAI ↔ Google ADK | 8002 | `app/protocols/a2a/` |
| **MCP** (Model Context Protocol) | Tool exposure to external consumers | 8001 | `app/tools/mcp/server.py` |

---

## Part 1 — A2A Protocol

### Why A2A?

The project mandates using **both CrewAI and Google ADK** — two incompatible agentic frameworks. A2A provides a standard HTTP-based protocol for cross-framework agent communication:

- CrewAI's `A2ARagTool` acts as the **A2A client** (sends tasks)
- The FastAPI server wrapping the ADK RAG agent acts as the **A2A server** (receives tasks)
- Communication uses structured JSON messages with request IDs, status codes, and error handling
- No Python function calls are disguised as A2A — real HTTP requests traverse the boundary

### A2A Server (ADK Side)

**Start the server:**
```powershell
cd e:\PRJ-4\mas_project
python -m app.protocols.a2a.server
# Listening on http://0.0.0.0:8002
```

**File:** `app/protocols/a2a/server.py`

#### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status": "ok", "agent": "rag_agent"}` |
| `GET` | `/.well-known/agent.json` | Agent capability card (discovery) |
| `POST` | `/a2a/task` | Submit a task to the ADK RAG agent |

#### Agent Card (`/.well-known/agent.json`)

```json
{
  "name": "rag_agent",
  "version": "1.0.0",
  "description": "Document RAG agent powered by Google ADK, FAISS, and sentence-transformers",
  "framework": "google-adk",
  "capabilities": ["document_retrieval", "semantic_search", "rag_qa"],
  "endpoint": "http://localhost:8002/a2a/task",
  "task_types": ["rag_query", "health_check"]
}
```

#### Task Submission (`POST /a2a/task`)

**Request body (`A2ATaskRequest`):**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_type": "rag_query",
  "payload": {
    "query": "What are the main findings in the uploaded report?",
    "top_k": 5,
    "session_id": "optional-session-id"
  },
  "sender_agent": "research_agent",
  "created_at": "2024-01-01T12:00:00Z"
}
```

**Response body (`A2ATaskResponse`):**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "COMPLETED",
  "result": {
    "answer": "The report's main findings include...",
    "excerpts": ["Finding 1 text", "Finding 2 text"],
    "document_ids": ["doc_abc123"],
    "chunk_ids": ["chunk_001", "chunk_002"],
    "scores": [0.89, 0.76],
    "success": true,
    "duration_ms": 487.3
  },
  "error": null,
  "completed_at": "2024-01-01T12:00:01Z"
}
```

**Error response:**
```json
{
  "task_id": "...",
  "status": "FAILED",
  "result": null,
  "error": "Vector store is empty — no documents indexed yet",
  "completed_at": "..."
}
```

#### Supported Task Types

| `task_type` | Description |
|-------------|-------------|
| `rag_query` | Semantic search + answer generation over indexed documents |
| `health_check` | Returns server status (no RAG invoked) |

---

### A2A Client (CrewAI Side)

**File:** `app/protocols/a2a/client.py`

#### `A2AClient`

Low-level HTTP client for sending tasks to the A2A server.

```python
from app.protocols.a2a.client import A2AClient

client = A2AClient(base_url="http://localhost:8002", timeout=30)

# Check server health
health = client.health_check()  # returns {"status": "ok", ...} or error dict

# Send a task
response = client.send_task(
    task_type="rag_query",
    payload={"query": "What is the main topic?", "top_k": 5},
    sender_agent="research_agent",
)
# response is an A2ATaskResponse object
print(response.status)   # "COMPLETED" | "FAILED"
print(response.result)   # dict with answer, excerpts, etc.
```

#### `A2ARagTool` — CrewAI Tool Wrapping A2A

This is the bridge: a `crewai.tools.BaseTool` subclass that calls the A2A server under the hood.

```python
from app.protocols.a2a.client import A2ARagTool

tool = A2ARagTool(a2a_base_url="http://localhost:8002")
result = tool._run("What does the document say about climate change?")
```

**Fallback behaviour:** If the A2A server is offline or unreachable, `A2ARagTool` falls back to a direct local vector store query. This ensures workflows degrade gracefully without crashing.

---

### End-to-End A2A Trace

```
CrewAI Workflow (hierarchical.py)
    │
    ├── Research Agent runs WebSearchTool
    │
    ├── A2ARagTool._run("query")          ← CrewAI side
    │       │
    │       │  HTTP POST http://localhost:8002/a2a/task
    │       │  Body: A2ATaskRequest JSON
    │       │
    │       ▼
    │   A2A FastAPI Server (server.py)    ← ADK side
    │       │
    │       ├── parse A2ATaskRequest
    │       ├── call run_adk_rag_agent_sync(query, vector_store)
    │       │       │
    │       │       └── LlmAgent (google.adk.agents.LlmAgent)
    │       │               uses _rag_retrieval_fn tool
    │       │               calls FAISS.search(query, top_k)
    │       │               generates answer with Gemini
    │       │
    │       └── return A2ATaskResponse JSON
    │
    └── CrewAI receives result dict
        Blackboard updated: bb.update_field(run_id, "rag_results", result)
```

---

### Running the Integration Test

First, start the A2A server in a separate terminal:
```powershell
cd e:\PRJ-4\mas_project
python -m app.protocols.a2a.server
```

Then run the integration tests:
```powershell
cd e:\PRJ-4\mas_project
python -m pytest tests/integration/test_a2a.py -v
```

**Offline tests** (always run, no server needed):
- `test_health_check_returns_dict` — client handles offline server gracefully
- `test_send_task_to_offline_server_returns_error_response` — error dict returned, not raised
- `test_a2a_rag_tool_fallback` — `A2ARagTool` falls back to local when server offline

**Live integration tests** (marked `@pytest.mark.integration`, skipped if server offline):
- `test_live_health_check` — real HTTP GET to server
- `test_live_rag_query` — real task submission + response

---

### A2A Schema Reference

**File:** `app/schemas/messages.py`

```python
class A2ATaskRequest(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    task_type: str                  # "rag_query" | "health_check"
    payload: dict                   # task-specific parameters
    sender_agent: str = "crewai_supervisor"
    created_at: datetime = ...

class A2ATaskResponse(BaseModel):
    task_id: str
    status: str                     # "COMPLETED" | "FAILED" | "PENDING"
    result: Optional[dict]
    error: Optional[str]
    completed_at: Optional[datetime]

class AgentCard(BaseModel):
    name: str
    version: str
    description: str
    framework: str
    capabilities: list[str]
    endpoint: str
    task_types: list[str]
```

---

## Part 2 — MCP (Model Context Protocol)

### Why MCP?

The faculty requirement mandates **at least two external tools exposed through MCP**. MCP provides a standardised protocol (using FastMCP / JSON-RPC) for exposing tools to any MCP-compatible consumer.

### Starting the MCP Server

```powershell
cd e:\PRJ-4\mas_project
python -m app.tools.mcp.server
# FastMCP server on http://localhost:8001
```

**File:** `app/tools/mcp/server.py`

### 4 Exposed MCP Tools

| Tool Name | Description | Key Parameters |
|-----------|-------------|---------------|
| `web_search` | DuckDuckGo search | `query`, `max_results` (default 5) |
| `document_retrieval` | FAISS semantic search | `query`, `top_k` (default 5) |
| `calculator` | Safe arithmetic evaluation | `expression` |
| `data_profiler` | pandas CSV profiling | `csv_path`, `operation` |

### Using MCP Tools Programmatically

```python
# The Research Agent uses WebSearchTool which internally calls DuckDuckGo
# The MCP server exposes the same tools for external/cross-agent consumption

# Direct programmatic use (for testing):
from app.tools.mcp.server import mcp
# Tools are registered via @mcp.tool() decorator
```

### MCP vs Direct Tool Calls

| Aspect | MCP | Direct Python call |
|--------|-----|-------------------|
| Protocol | JSON-RPC over HTTP | Python function call |
| Discovery | Standardised schema listing | Manual documentation |
| Cross-language | Yes (any MCP client) | No |
| Overhead | Slight HTTP latency | Minimal |
| Auditability | Tool calls logged via protocol | Depends on implementation |

MCP enables tools to be consumed by external systems (other agents, notebooks, monitoring dashboards) without tight coupling to the Python codebase.

---

## Starting All Services

Use the provided script to start both servers:
```powershell
cd e:\PRJ-4\mas_project
.\scripts\run_all_servers.ps1
```

Or individually:
```powershell
# Terminal 1 — A2A server
python -m app.protocols.a2a.server

# Terminal 2 — MCP server
python -m app.tools.mcp.server

# Terminal 3 — Streamlit UI
streamlit run app/ui/app.py
```

Health check both:
```powershell
Invoke-WebRequest http://localhost:8002/health | Select-Object -Expand Content
Invoke-WebRequest http://localhost:8001/ | Select-Object -Expand StatusCode
```
