# Evaluation Methodology

## Research Question

> *"Can a multi-agent AI system combining specialized agents, Retrieval-Augmented Generation (RAG), external tools, and agent-to-agent coordination improve accuracy, reliability, and task-completion performance on complex knowledge-based queries compared with a single-LLM baseline?"*

---

## Hypotheses

These are **hypotheses to test** — not pre-claimed results. Findings may be positive, negative, or inconclusive.

| ID | Hypothesis |
|----|-----------|
| **H1** | The multi-agent system (HIERARCHICAL pattern) improves task completion and answer correctness compared with a single-LLM baseline (BASELINE pattern). |
| **H2** | RAG improves evidence relevance and groundedness for questions about uploaded documents compared with retrieval-free patterns. |
| **H3** | Specialised agents and appropriate coordination patterns improve task success on multi-step tasks, with potential trade-offs in latency and cost. |

---

## Test Cases

**File:** `evaluation_data/test_cases/all_cases.json`

**Total:** 50 test cases across 9 categories.

| Category | Code | Count | Description |
|----------|------|-------|-------------|
| Factual | F | 8 | Single-answer factual questions |
| Research | R | 8 | Multi-source research synthesis |
| Document QA | D | 7 | Requires RAG over uploaded documents |
| Data Analysis | DA | 6 | CSV / tabular data questions |
| Multi-agent | MA | 6 | Complex tasks needing ≥2 agents |
| Insufficient Evidence | IE | 5 | Questions with no good answer |
| Conflicting Sources | CS | 5 | Deliberately contradictory evidence |
| Security | SEC | 3 | Injection / jailbreak attempts |
| Malformed Input | MI | 2 | Edge cases (empty, too long, binary) |

### Test Case Schema

```json
{
  "id": "F001",
  "category": "F",
  "query": "What is the speed of light in a vacuum?",
  "reference_answer": "299,792,458 metres per second",
  "persona": "RESEARCHER",
  "expected_pattern": "BASELINE",
  "difficulty": "easy",
  "tags": ["physics", "factual"]
}
```

---

## Workflow Patterns Tested

| Pattern | Description | Agents |
|---------|-------------|--------|
| `BASELINE` | Single LLM call, no tools, no RAG | 1 (baseline_llm) |
| `HIERARCHICAL` | Supervisor → Research → RAG → Synthesis → Critic | 4–5 |
| `PARALLEL` | Research ‖ RAG simultaneously → Synthesis → Critic | 4–5 |
| `SEQUENTIAL` | RAG → Critic verify → Synthesis (strict order) | 3–4 |

---

## Metrics

### Primary Metrics

| Metric | How Measured | Notes |
|--------|-------------|-------|
| **Correctness Score** | Keyword overlap between answer and reference | Heuristic — not ground truth |
| **Groundedness Score** | Presence of citations, sources, evidence | Heuristic — not formal faithfulness |
| **Completion Rate** | % runs that return a non-error FinalResponse | Objective |
| **Latency (ms)** | Wall-clock time from query to FinalResponse | Objective |

### Secondary Metrics

| Metric | Notes |
|--------|-------|
| `total_tokens` | Input + output tokens (estimated) |
| `cost_estimate_usd` | Based on published pricing — labelled as estimate |
| `verification_status` | PASS / NEEDS_REVISION / INSUFFICIENT_EVIDENCE |
| `is_mock` | Must be `False` for valid evaluation runs |
| `agents_used` | Which agents participated |

> [!WARNING]
> **Correctness and groundedness scores are heuristics, not validated metrics.**
> They use simple keyword matching and citation presence checks.
> Do NOT present these as formal NLP evaluation scores (e.g., BLEU, ROUGE, BERTScore).
> Human evaluation or validated annotation would be required for rigorous claims.

---

## Running the Evaluation

### Prerequisites
- `.env` configured with a valid `GOOGLE_API_KEY`
- `CREWAI_LLM_MODEL` set to an available model

### Quick Run (10 cases × 2 patterns = 20 runs)

```powershell
cd e:\PRJ-4\mas_project
python -m app.evaluation.harness --patterns BASELINE HIERARCHICAL --limit 10
```

### Full Run (≥40 runs for faculty requirement)

```powershell
# Batch 1: BASELINE + HIERARCHICAL (25 cases each = 50 runs)
python -m app.evaluation.harness --patterns BASELINE HIERARCHICAL --limit 25

# Batch 2: PARALLEL + SEQUENTIAL (13 cases each = 26 runs)
python -m app.evaluation.harness --patterns PARALLEL SEQUENTIAL --limit 13
# Total: 76 runs
```

### All Patterns, All Cases (200 runs)

```powershell
python -m app.evaluation.harness --all
```

### Dry Run (no API calls — verify harness works)

```powershell
python -m app.evaluation.harness --patterns BASELINE --limit 3 --dry-run
```

---

## Output Files

All results are saved to `evaluation_data/results/`:

| File | Format | Contents |
|------|--------|---------|
| `results_YYYYMMDD_HHMMSS.json` | JSON | Full EvaluationRecord list |
| `results_YYYYMMDD_HHMMSS.csv` | CSV | Flat table for spreadsheet analysis |
| `charts/latency_boxplot.png` | PNG | Latency distribution per pattern |
| `charts/agent_heatmap.png` | PNG | Agent usage × query category |
| `charts/completion_bar.png` | PNG | Completion rate per pattern |

---

## Generating Charts

```python
from app.evaluation.charts import generate_all_charts, load_all_results

records = load_all_results("evaluation_data/results")
paths = generate_all_charts(records, output_dir="evaluation_data/results/charts")
print(paths)
# {"latency_boxplot": "...", "agent_heatmap": "...", "completion_bar": "..."}
```

Or from the Streamlit UI: **Evaluation** page → "Generate Charts" button.

---

## EvaluationRecord Schema

```python
class EvaluationRecord(BaseModel):
    record_id: str              # UUID
    run_id: str                 # Blackboard run_id
    test_case_id: str           # e.g. "F001"
    category: str               # "F" | "R" | "D" | "DA" | "MA" | "IE" | "CS" | "SEC" | "MI"
    query: str
    reference_answer: Optional[str]
    workflow_pattern: str
    persona: str
    answer: str                 # actual system answer
    correctness_score: Optional[float]    # 0.0–1.0, heuristic
    groundedness_score: Optional[float]   # 0.0–1.0, heuristic
    latency_ms: float
    total_tokens: int
    cost_estimate_usd: float
    completion_success: bool
    is_mock: bool
    verification_status: str
    agents_used: list[str]
    sources_count: int
    evidence_count: int
    config_hash: str            # reproducibility hash of key settings
    model_used: str
    timestamp: str
```

---

## Interpreting Results

### H1 (Multi-agent vs Baseline)

Compare `correctness_score` and `completion_success` between `BASELINE` and `HIERARCHICAL` patterns using:
- Mean and median correctness
- Box plots of latency distributions
- Completion rate bar chart

**Honest reporting:** If HIERARCHICAL does not outperform BASELINE on correctness, report this honestly. The latency/cost trade-off may still be unfavourable.

### H2 (RAG Groundedness)

Compare `groundedness_score` between:
- `HIERARCHICAL` (uses RAG via A2A) on category `D` (document QA) test cases
- `BASELINE` on same cases

**Honest reporting:** If no documents are indexed, the RAG agent returns "no documents found" — this is the correct and honest behaviour and should be reported.

### H3 (Pattern Trade-offs)

Compare HIERARCHICAL vs PARALLEL vs SEQUENTIAL on:
- `MA` (multi-agent) category — where coordination matters most
- Latency (PARALLEL should be faster than SEQUENTIAL)
- Cost (more agents = more tokens = higher cost estimate)

---

## Limitations

1. **Heuristic scoring** — correctness/groundedness are not human-evaluated
2. **Small test set** — 50 cases × 4 patterns = 200 max runs; not statistically robust for all subcategories
3. **DuckDuckGo rate limits** — web search may return 0 results under load; this affects research-dependent scores
4. **No ground truth for complex queries** — for open-ended research questions, "correct" is subjective
5. **Single model** — all runs use one model; results may differ with other models
6. **Mock mode** — any run with `is_mock=True` must be excluded from evaluation results
7. **Cost estimates** — not actual billed amounts; token counting is approximate

---

## Faculty Requirement: ≥40 Runs

The minimum requirement is 40 runs with real LLM calls (`is_mock=False`).

**Recommended breakdown:**
- 25 runs × BASELINE = 25
- 25 runs × HIERARCHICAL = 25
- **Total = 50 runs** (exceeds 40 minimum)

Add PARALLEL and SEQUENTIAL for 100 runs if time permits.

