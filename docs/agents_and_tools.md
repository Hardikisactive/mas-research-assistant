# Agents and Tools Reference

## Overview

The system uses **6 logical agents** split across two frameworks:
- **CrewAI** — Supervisor, Research, Data Analysis, Critic, Synthesis
- **Google ADK** — RAG Agent (communicates via A2A protocol)

---

## Agent 1: Supervisor / Orchestrator

| Attribute | Value |
|-----------|-------|
| Framework | CrewAI |
| File | `app/agents/supervisor/agent.py` |
| Role | Orchestration, task planning, workflow routing |

### Responsibilities
- Parse and classify the user query (research / document QA / data analysis / mixed)
- Select which agents are needed and choose a workflow pattern
- Create a structured task plan
- Coordinate Blackboard state updates
- Handle timeouts, retries, partial failures
- Route failed or critic-rejected results for revision

### Input
```python
query: str          # sanitized user query
persona: str        # RESEARCHER | STUDENT | ANALYST | EXPERT | GENERAL
```

### Output
```python
{
  "task_type": "RESEARCH | DOC_QA | DATA_ANALYSIS | MIXED",
  "agents_needed": ["research", "rag", "data_analysis", "critic", "synthesis"],
  "workflow_pattern": "HIERARCHICAL | PARALLEL | SEQUENTIAL",
  "plan": "Step-by-step coordination plan string"
}
```

### Tools Used
- None directly — coordinates other agents' tools

### Key Method
```python
classify_query(query: str) -> dict
```
Heuristic classification using keyword matching (no LLM call required in mock mode).

---

## Agent 2: Research Agent

| Attribute | Value |
|-----------|-------|
| Framework | CrewAI |
| File | `app/agents/research/agent.py` |
| Role | External web research using search tools |

### Responsibilities
- Search the web via DuckDuckGo (no API key required)
- Collect source URLs, titles, timestamps, and evidence extracts
- Distinguish verified facts from uncertain claims
- Use a ReAct-style tool-use loop: *Action → Observation → Decision*
- Record all tool calls in the Blackboard

### Input
```python
query: str          # research sub-question from Supervisor
max_results: int    # default 5
```

### Output
```python
{
  "sources": [
    {
      "url": "https://...",
      "title": "Source Title",
      "snippet": "Relevant excerpt...",
      "retrieved_at": "ISO timestamp"
    }
  ],
  "summary": "Combined research summary",
  "confidence": "HIGH | MEDIUM | LOW"
}
```

### Tools Used
| Tool | Source | Description |
|------|--------|-------------|
| `WebSearchTool` | `duckduckgo_search` | Searches DuckDuckGo, returns titles + snippets + URLs |
| `A2ARagTool` | `app/protocols/a2a/client.py` | Optionally retrieves from indexed documents via A2A |

---

## Agent 3: Document RAG Agent (Google ADK)

| Attribute | Value |
|-----------|-------|
| Framework | **Google ADK** (`google.adk.agents.LlmAgent`) |
| File | `app/agents/rag/adk_agent.py` |
| Communication | Via A2A protocol (HTTP POST to `http://localhost:8002/a2a/task`) |
| Role | Retrieval-Augmented Generation over uploaded documents |

### Responsibilities
- Accept queries about uploaded PDFs/TXT/DOCX/JSON files
- Search the FAISS vector index for relevant chunks
- Return: answer, supporting excerpts, document IDs, chunk IDs, relevance scores
- Report honestly when no relevant evidence is found

### Input (A2A Task Request)
```json
{
  "task_id": "uuid",
  "task_type": "rag_query",
  "payload": {
    "query": "What does the document say about X?",
    "top_k": 5,
    "session_id": "optional-session-id"
  }
}
```

### Output (A2A Task Response)
```json
{
  "task_id": "uuid",
  "status": "COMPLETED",
  "result": {
    "answer": "Based on the document...",
    "excerpts": ["chunk text 1", "chunk text 2"],
    "document_ids": ["doc_abc123"],
    "chunk_ids": ["chunk_001", "chunk_002"],
    "scores": [0.87, 0.74],
    "success": true,
    "duration_ms": 342.1
  }
}
```

### Tools Used
| Tool | Description |
|------|-------------|
| `_rag_retrieval_fn` (ADK FunctionTool) | Searches FAISS index, returns chunks with scores |

### ADK Construction
```python
agent = LlmAgent(
    name="rag_agent",
    description="Document retrieval agent using FAISS and sentence-transformers",
    instruction="...",
    model="gemini-1.5-flash",
    tools=[_build_rag_retrieval_tool(vector_store)],
    output_schema=None,
)
```

---

## Agent 4: Data Analysis Agent

| Attribute | Value |
|-----------|-------|
| Framework | CrewAI |
| File | `app/agents/data_analysis/agent.py` |
| Role | Structured analysis of CSV / tabular data |

### Responsibilities
- Accept CSV files from `data/uploads/`
- Inspect schema, dtypes, missing values, basic statistics
- Clean data conservatively and report transformations
- Run allowlisted pandas operations (no arbitrary code execution)
- Return calculations, assumptions, metrics, summaries
- Optionally apply Scikit-learn (clustering, regression) when appropriate

### Input
```python
csv_path: str       # validated path under data/uploads/
query: str          # analysis question
operations: list    # allowlisted: ["describe", "head", "dtypes", "missing", "corr", "value_counts"]
```

### Output
```python
{
  "schema": {"column": "dtype", ...},
  "row_count": 1000,
  "missing_values": {"col": 5, ...},
  "statistics": { ... },
  "analysis_result": "Narrative analysis string",
  "transformations_applied": ["dropped 3 rows with null values in 'temp'"]
}
```

### Tools Used
| Tool | Description |
|------|-------------|
| `DataAnalysisTool` | Allowlisted pandas operations — no `eval()`, no shell commands |

### Security
Path traversal protection via `validate_csv_path()` — only files under `data/uploads/` are accessible.

---

## Agent 5: Critic / Verification Agent

| Attribute | Value |
|-----------|-------|
| Framework | CrewAI |
| File | `app/agents/critic/agent.py` |
| Role | Cross-check claims against retrieved evidence |

### Responsibilities
- Check research or RAG output claims against sources
- Identify: unsupported claims, contradictions, missing citations, insufficient evidence
- Return structured verdict: `PASS | NEEDS_REVISION | INSUFFICIENT_EVIDENCE`
- Never treat LLM confidence alone as proof — require source checks

### Input
```python
content_to_verify: str      # synthesis draft or research summary
sources: list[SourceRecord] # evidence to check against
claims: list[str]           # specific claims to verify
```

### Output
```python
{
  "status": "PASS | NEEDS_REVISION | INSUFFICIENT_EVIDENCE",
  "issues": [
    {
      "claim": "X causes Y",
      "issue": "No source found supporting this",
      "recommendation": "Remove or qualify this claim"
    }
  ],
  "verified_claims": ["Claim A is supported by source 1"],
  "confidence": "HIGH | MEDIUM | LOW"
}
```

### Key Method
```python
parse_critic_output(raw: str) -> dict
```
Deterministic regex-based parsing of the LLM critic output into structured verdict.

---

## Agent 6: Synthesis Agent

| Attribute | Value |
|-----------|-------|
| Framework | CrewAI |
| File | `app/agents/synthesis/agent.py` |
| Role | Combine all agent outputs into a final validated response |

### Responsibilities
- Combine research + RAG + data analysis results
- Produce final response in `FinalResponse` Pydantic schema
- Include citations and document references when available
- State limitations and missing evidence explicitly
- Never silently resolve conflicting evidence into a definite conclusion

### Input
```python
research_results: dict
rag_results: dict
data_analysis_results: dict
verification_result: dict
query: str
```

### Output (`FinalResponse` Pydantic model)
```python
class FinalResponse(BaseModel):
    run_id: str
    query: str
    sanitized_query: str
    answer: str                          # main narrative answer
    findings: list[Finding]              # structured claims with evidence
    sources: list[SourceRecord]          # web sources
    evidence: list[EvidenceRecord]       # document evidence
    data_analysis: Optional[DataAnalysisResult]
    verification_status: VerificationStatus
    limitations: list[str]
    agents_used: list[str]
    execution_summary: ExecutionSummary  # tokens, cost estimate, latency
    is_mock: bool                        # True if no API key configured
```

---

## MCP Tools

The MCP server runs separately at `http://localhost:8001` and exposes 4 tools via the FastMCP protocol.

Start: `python -m app.tools.mcp.server`

### Tool 1: `web_search`

| Attribute | Value |
|-----------|-------|
| File | `app/tools/mcp/server.py` |
| Engine | DuckDuckGo (no API key required) |

**Parameters:**
```json
{
  "query": "string — search query",
  "max_results": "integer — default 5, max 20"
}
```

**Returns:**
```json
{
  "results": [
    {
      "title": "Page title",
      "url": "https://...",
      "snippet": "Brief excerpt",
      "retrieved_at": "ISO 8601 timestamp"
    }
  ],
  "query": "original query",
  "result_count": 5
}
```

---

### Tool 2: `document_retrieval`

| Attribute | Value |
|-----------|-------|
| File | `app/tools/mcp/server.py` |
| Engine | FAISS + sentence-transformers (`all-MiniLM-L6-v2`) |

**Parameters:**
```json
{
  "query": "string — semantic search query",
  "top_k": "integer — default 5, max 20"
}
```

**Returns:**
```json
{
  "chunks": [
    {
      "text": "Relevant text excerpt",
      "document_id": "doc_abc123",
      "chunk_id": "chunk_001",
      "score": 0.87,
      "metadata": {}
    }
  ],
  "query": "original query",
  "result_count": 5
}
```

---

### Tool 3: `calculator`

| Attribute | Value |
|-----------|-------|
| File | `app/tools/mcp/server.py` |
| Engine | Safe math eval (restricted to arithmetic + math functions) |

**Parameters:**
```json
{ "expression": "string — e.g. '2 ** 10 + sqrt(16)'" }
```

**Returns:**
```json
{ "expression": "2 ** 10 + sqrt(16)", "result": 1028.0 }
```

> [!WARNING]
> Only safe math operations are permitted. Shell commands, `import`, and `exec` are blocked by `validate_expression()`.

---

### Tool 4: `data_profiler`

| Attribute | Value |
|-----------|-------|
| File | `app/tools/mcp/server.py` |
| Engine | pandas |

**Parameters:**
```json
{
  "csv_path": "string — path relative to data/uploads/",
  "operation": "string — one of: describe, head, dtypes, missing, shape"
}
```

**Returns:**
```json
{
  "operation": "describe",
  "result": { "column_stats": { ... } },
  "rows": 1000,
  "columns": 15
}
```

---

## Communication Flow

```
User Query
    │
    ▼
Workflow Engine (run_workflow)
    │  apply guardrails
    │  create Blackboard run
    ▼
Supervisor Agent (CrewAI) ──────────────────┐
    │  classify + plan                       │
    ▼                                        │
Research Agent (CrewAI)           ◄──────────┤ Blackboard
    │  WebSearchTool (DuckDuckGo)            │ shared state
    ▼                                        │
A2A Client ─── HTTP POST ──► A2A Server ────┤
                              (port 8002)    │
                              ADK RAG Agent ─┘
    │
    ▼
Data Analysis Agent (CrewAI)
    │  DataAnalysisTool (pandas)
    ▼
Critic Agent (CrewAI)
    │  verify claims vs sources
    ▼
Synthesis Agent (CrewAI)
    │  FinalResponse (Pydantic)
    ▼
Blackboard updated → UI rendered
```
