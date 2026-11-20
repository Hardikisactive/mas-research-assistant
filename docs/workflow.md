# Workflow Patterns

## Overview

The system implements four workflow patterns. The Workflow Engine (`app/workflows/engine.py`) routes each query to the appropriate pattern based on the `pattern` parameter.

| Pattern | Use Case | Agents | Approx. Time |
|---------|---------|--------|-------------|
| `BASELINE` | Comparison baseline, simple factual | 1 (LLM only) | 2–5s |
| `SEQUENTIAL` | Document Q&A requiring verification | 3–4 | 15–25s |
| `PARALLEL` | Research + document retrieval simultaneously | 4–5 | 15–25s |
| `HIERARCHICAL` | Complex multi-step research | 4–5 | 25–45s |

---

## Pattern 1: BASELINE

**File:** `app/workflows/baseline.py`

A single Gemini API call with no tools, no RAG, no multi-agent orchestration. Used as the **comparison baseline** for H1 hypothesis testing.

```
User Query
    │
    ▼
validate_query()
    │
    ▼
Single Gemini LLM call
("Answer from training knowledge only")
    │
    ▼
FinalResponse (is_mock=False, agents_used=["baseline_llm"])
```

**Blackboard fields set:** `current_status`, `final_answer`

**Limitations recorded:** "No retrieval", "No fact-checking", "Single LLM baseline"

---

## Pattern 2: SEQUENTIAL

**File:** `app/workflows/sequential.py`

Agents run in strict sequence — each agent's output feeds the next. Best for document Q&A where verification is critical before synthesis.

```
User Query → validate_query() → Blackboard run created
    │
    ▼
[Step 1] RAG Agent (ADK via A2A)
    │  retrieves document chunks
    │  writes → Blackboard["rag_results"]
    ▼
[Step 2] Critic Agent (CrewAI)
    │  verifies RAG answer against source chunks
    │  if NEEDS_REVISION → retry RAG with clarified query
    │  writes → Blackboard["verification_results"]
    ▼
[Step 3] Synthesis Agent (CrewAI)
    │  combines RAG + verification
    │  produces FinalResponse
    ▼
FinalResponse
```

**Sequence Diagram:**
```
Engine      RAG(ADK)    Critic(CrewAI)   Synthesis(CrewAI)
  │─────────────►│
  │  A2A task    │
  │◄─────────────│
  │  RAG result  │
  │──────────────────────►│
  │              Verify   │
  │◄──────────────────────│
  │              PASS/FAIL│
  │─────────────────────────────────────►│
  │                              Synthesise
  │◄─────────────────────────────────────│
  │                              FinalResponse
```

---

## Pattern 3: PARALLEL

**File:** `app/workflows/parallel.py`

Research and RAG run simultaneously in separate threads. Once both complete, results are merged and passed to Synthesis → Critic.

```
User Query → validate_query() → Blackboard run created
    │
    ├──────────────────┬──────────────────┐
    ▼                  ▼                  │
[Thread 1]         [Thread 2]             │
Research Agent     RAG Agent (ADK)        │
(DuckDuckGo)       (A2A → FAISS)         │
    │                  │                  │
    ▼                  ▼                  │
research_results   rag_results  ─────────►│
(Blackboard)       (Blackboard)           │
    │                                     │
    └──────────────────────────────────── ┘
                    │
                    ▼ (both threads joined)
           [Synthesis Agent] (CrewAI)
                    │
                    ▼
           [Critic Agent] (CrewAI)
                    │
                    ▼
             FinalResponse
```

**Thread safety:** Both threads write to different Blackboard fields — no conflict. The main thread waits with `thread.join(timeout=60)`.

---

## Pattern 4: HIERARCHICAL

**File:** `app/workflows/hierarchical.py`

The full pipeline with a Supervisor orchestrating all agents. Best for complex research queries requiring multiple information sources.

```
User Query → validate_query() → Blackboard run created
    │
    ▼
[Supervisor Agent] (CrewAI)
    classify_query() → task_type, agents_needed, workflow_pattern
    writes → Blackboard["plan"]
    │
    ▼
[Research Agent] (CrewAI)
    WebSearchTool → DuckDuckGo
    ReAct loop: search → observe → refine (max 5 iterations)
    writes → Blackboard["research_results"]
    │
    ▼
[A2A RAG Call] (CrewAI → ADK via HTTP)
    A2ARagTool → POST http://localhost:8002/a2a/task
    ADK LlmAgent → FAISS search → Gemini answer
    writes → Blackboard["rag_results"]
    │
    ▼
[Data Analysis Agent] (CrewAI) ← only if CSV in query
    DataAnalysisTool → pandas allowlisted ops
    writes → Blackboard["data_analysis_results"]
    │
    ▼
[Critic Agent] (CrewAI)
    Verifies research + RAG claims against sources
    PASS / NEEDS_REVISION / INSUFFICIENT_EVIDENCE
    writes → Blackboard["verification_results"]
    │
    ▼
[Synthesis Agent] (CrewAI)
    Combines all results → FinalResponse (Pydantic)
    writes → Blackboard["final_answer"]
    │
    ▼
FinalResponse returned to user
```

---

## Engine Routing

**File:** `app/workflows/engine.py`

```python
def run_workflow(
    query: str,
    pattern: str = "HIERARCHICAL",
    persona: str = "RESEARCHER",
    conversation_id: Optional[str] = None,
) -> FinalResponse:
```

Steps:
1. `validate_query(query)` — guardrails, returns `sanitized_query`
2. `bb.create_run(...)` — creates Blackboard entry with unique `run_id`
3. `get_metrics().start_run(run_id)` — starts metrics collection
4. Route to pattern: `hierarchical` / `parallel` / `sequential` / `baseline`
5. Return `FinalResponse` — always returned, even on error (never raises)

**Mock mode:** When no API key is configured (`settings.has_llm_configured() == False`), all patterns return `is_mock=True` with stub answers. This allows testing without API keys.

---

## Workflow Pattern Comparison

| Metric | BASELINE | SEQUENTIAL | PARALLEL | HIERARCHICAL |
|--------|---------|-----------|---------|------------|
| Agents | 1 | 3–4 | 4–5 | 4–5 |
| Web Search | ❌ | ❌ | ✅ | ✅ |
| RAG | ❌ | ✅ | ✅ | ✅ |
| Data Analysis | ❌ | ❌ | ❌ | ✅ (if CSV) |
| Verification | ❌ | ✅ | ✅ | ✅ |
| Approx. Tokens | ~500 | ~2000 | ~2500 | ~3000 |
| Latency | Fastest | Medium | Medium | Slowest |
| Best for | Comparison | Doc Q&A | Research | Complex queries |

