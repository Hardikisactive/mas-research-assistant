# Viva / Faculty Interview Questions and Answers

## System Architecture

---

**Q1. Why did you use both CrewAI and Google ADK instead of just one framework?**

The faculty requirement explicitly mandates using both. Beyond compliance, it demonstrates cross-framework interoperability — a realistic engineering challenge in production AI systems where different teams or vendors use different frameworks. CrewAI excels at orchestrating multi-step agentic pipelines with tools, tasks, and crews. Google ADK provides a native integration path for Gemini models and a clean abstractions for tool-using LLM agents. The separation also enforces a meaningful responsibility boundary: CrewAI handles orchestration and research, ADK handles document retrieval.

---

**Q2. How does A2A work in your project? Is it real inter-process communication?**

Yes — it is real HTTP communication. The Google ADK RAG agent runs inside a FastAPI server (`app/protocols/a2a/server.py`) on port 8002. The CrewAI side has an `A2ARagTool` that makes an actual HTTP POST request to `http://localhost:8002/a2a/task` with a JSON body containing a `task_id`, `task_type`, and `payload`. The server processes the request using the ADK `LlmAgent`, searches FAISS, generates an answer, and returns a JSON `A2ATaskResponse`. The CrewAI tool then parses this response and returns it to the Research Agent as a string result. This crosses a real process boundary (different threads, different port, HTTP protocol) — it is not Python function calls renamed as A2A.

---

**Q3. What is the Blackboard pattern and why use it instead of passing data between agents directly?**

The Blackboard is a shared persistent data store (SQLite) that all agents read from and write to. Rather than Agent A calling Agent B directly and passing data, Agent A writes its results to a named field in the Blackboard, and Agent B reads from that field when it needs the data. This provides: (1) **Decoupling** — agents don't need to know about each other; (2) **Persistence** — state survives agent restarts or failures; (3) **Auditability** — every write is logged with who changed what and when; (4) **Parallelism** — parallel agents can safely write to different fields simultaneously.

---

**Q4. How do you ensure thread safety in the Blackboard when parallel agents run?**

The `Blackboard` class holds a `threading.RLock`. Every write method (`update_field`, `append_to_list_field`, `record_event`, `record_tool_call`) acquires this lock before any SQLite write and releases it after. Additionally, SQLite is configured with WAL (Write-Ahead Logging) mode which allows concurrent readers while a writer holds the lock. In the PARALLEL workflow, Research and RAG agents run in separate threads but write to different Blackboard fields (`research_results` vs `rag_results`), so there is no field-level conflict. Tested with 20 concurrent threads doing 100 updates each — all 2000 updates succeed with correct versioning.

---

**Q5. What is RAG and how is it implemented here?**

RAG (Retrieval-Augmented Generation) augments LLM answers with evidence retrieved from a local document corpus. Implementation: (1) User uploads a PDF/TXT/DOCX/JSON document; (2) `document_processor.py` extracts text and splits it into 500-token chunks with 50-token overlap; (3) `vector_store.py` embeds each chunk using `sentence-transformers` (`all-MiniLM-L6-v2`) and stores embeddings in a FAISS index; (4) At query time, the ADK RAG agent calls the `_rag_retrieval_fn` tool which embeds the query and retrieves the top-K most similar chunks from FAISS; (5) The LlmAgent generates an answer conditioned on those chunks. The key advantage over pure LLM is that the answer is grounded in the actual document content rather than training data.

---

**Q6. What are your three hypotheses and what did the evaluation show?**

- **H1** (multi-agent improves correctness vs baseline): The HIERARCHICAL pattern used web search and multiple reasoning passes, often producing more detailed answers. However, correctness *scores* (keyword heuristics) were mixed — the baseline sometimes scored equally because both contained the right keywords. The HIERARCHICAL pattern showed higher groundedness scores due to citations. Conclusive claim requires human evaluation.
- **H2** (RAG improves groundedness for document questions): When documents were indexed, RAG-enabled patterns returned document excerpts with chunk IDs and scores — clearly higher groundedness. When no documents were indexed, the system honestly reported "no documents found" rather than hallucinating.
- **H3** (pattern trade-offs in latency/cost): PARALLEL was faster than SEQUENTIAL for multi-source queries (parallel research + RAG). HIERARCHICAL had the highest token count and cost due to multiple agent invocations. BASELINE was fastest and cheapest but least grounded.

---

**Q7. How do your guardrails prevent prompt injection?**

`validate_query()` checks every incoming query against a regex blocklist of 10+ injection patterns before any agent sees it. Patterns include: "ignore previous instructions", "you are now an unrestricted AI", "enable DAN mode", template injection `{{...}}`, and more. If matched, a `GuardrailViolation` exception is raised immediately and a REJECTED response is returned without any LLM call. Additionally, retrieved web content passes through `validate_retrieved_content()` which scans for the same patterns — but does not reject legitimate research content; instead it flags the content with a warning so the agent knows to treat it cautiously.

---

**Q8. What is MCP and how does it differ from calling tools directly in Python?**

MCP (Model Context Protocol) is a standardised JSON-RPC protocol for exposing tools to AI agents. Instead of hard-coding tool calls as Python function imports, tools are registered on an MCP server and exposed via a discoverable schema. Any MCP-compatible client (different agent frameworks, notebooks, monitoring systems) can call the same tools without knowing the implementation. Our MCP server (`app/tools/mcp/server.py`) exposes 4 tools: `web_search`, `document_retrieval`, `calculator`, `data_profiler`. The key benefit is interoperability and separation of concerns — tools can be updated, versioned, or replaced without changing agent code.

---

**Q9. How do you make cost estimates honest?**

Cost estimates are clearly labelled as *estimates* throughout the codebase and UI. The `pricing.py` module returns a dict with a `"label"` field always reading `"estimate — not actual billing"`. The `cost_model_label` in settings includes "(estimate, Oct 2026)". The evaluation documentation explicitly states that token counting is approximate and actual billing may differ. We never claim to show exact API costs — only order-of-magnitude estimates for comparison purposes.

---

**Q10. What would you change to scale this to production?**

1. **Replace SQLite Blackboard with PostgreSQL** — for concurrent multi-user workloads
2. **Replace in-memory FAISS with a managed vector database** (Vertex AI Vector Search or Pinecone) — for persistence across container restarts
3. **Move uploaded documents to Cloud Storage** — so they survive ephemeral container instances
4. **Add authentication** (Cloud IAP or OAuth2) — instead of `--allow-unauthenticated`
5. **Cache embeddings** — avoid re-embedding the same document chunks repeatedly
6. **Add rate limiting** — per-user quotas to control API costs
7. **Use async CrewAI** — for better throughput under concurrent users

---

**Q11. Why does the Data Analysis Agent not execute arbitrary Python code?**

Security. If we allowed arbitrary Python execution, a user could upload a CSV and ask: "Run `os.system('rm -rf /')`" or exfiltrate environment variables. Instead, `DataAnalysisTool` only supports an allowlisted set of pandas operations (`describe`, `head`, `dtypes`, `missing`, `corr`, `value_counts`, `shape`). The `validate_csv_path()` function prevents path traversal attacks. The `validate_expression()` function restricts the calculator to pure arithmetic. These controls prevent code injection while still providing meaningful data analysis capabilities.

---

**Q12. How does the Critic Agent work? Does it just trust the LLM's confidence?**

No — the Critic explicitly uses `parse_critic_output()`, a deterministic regex parser that extracts the verdict (`PASS`, `NEEDS_REVISION`, `INSUFFICIENT_EVIDENCE`) from the LLM's output. The LLM's confidence alone is not treated as proof. The Critic checks whether specific claims are supported by specific sources in the evidence list. If a claim has no corresponding source, it flags it as unsupported. The system records `INSUFFICIENT_EVIDENCE` when sources are absent rather than presenting uncertain claims as facts.

---

**Q13. How do you handle the case when the ADK A2A server is offline?**

`A2ARagTool` implements a graceful fallback. When the HTTP request to the A2A server fails (connection refused, timeout, HTTP error), instead of crashing the workflow, it falls back to a direct local FAISS query — bypassing A2A but still returning RAG results. The fallback result includes a `"fallback": true` flag so the Blackboard records this degraded behaviour. The Workflow Inspector in the Streamlit UI shows whether A2A was used or the fallback was activated.

---

**Q14. What is the difference between the HIERARCHICAL and PARALLEL patterns?**

In **HIERARCHICAL**, agents run sequentially in a fixed order: Research → RAG → DataAnalysis → Synthesis → Critic. Each agent waits for the previous one to complete before starting. This maximises the chance that each agent can use results from the previous one (e.g., Synthesis can combine research + RAG results) but is slower.

In **PARALLEL**, Research and RAG run simultaneously in separate threads. Once both complete, their combined results are passed to Synthesis → Critic. This is faster for queries that need both web research and document retrieval, since those two tasks don't depend on each other. The trade-off is that the Research agent cannot use RAG results to refine its search, and vice versa.

---

**Q15. How do you know the system is actually calling Gemini and not mocking?**

Every `FinalResponse` has an `is_mock: bool` field. When `GOOGLE_API_KEY` is not configured, the system returns `is_mock=True` and prepends `[Mock]` to the answer. When the API is configured and called, `is_mock=False`. The evaluation harness filters out `is_mock=True` runs from valid results. The Blackboard stores the actual LLM model name used. You can also verify by checking the Streamlit UI's Settings page → Health Check, which makes a live API call and shows the response time.

---

**Q16. What is the ReAct pattern and where is it used?**

ReAct (Reasoning + Acting) is a pattern where the agent alternates between reasoning (thinking about what to do) and acting (calling a tool), then observing the result. It loops until it has enough information to produce a final answer. In this project, the Research Agent uses CrewAI's built-in ReAct loop: it reasons about the query, calls `WebSearchTool`, observes the results, decides if more searches are needed, calls again if necessary, and finally synthesises a research summary. The agent's `max_iter=5` limits the loop to 5 reasoning/acting cycles to prevent infinite loops.

---

**Q17. Why does the evaluation use keyword-match correctness instead of BLEU or ROUGE?**

BLEU and ROUGE measure n-gram overlap between generated text and a reference — they are designed for machine translation and summarisation where a reference is a near-perfect gold standard. For open-ended research questions, there is rarely one correct phrasing of the answer. Keyword-match (do the key facts appear in the answer?) is a weaker but more appropriate heuristic for this task. We explicitly label these as *heuristic scores*, not formal NLP metrics. Human evaluation would be required for rigorous claims. BERTScore or G-Eval would be better automated alternatives for future work.

---

**Q18. What is provenance and how do you track it?**

Provenance is the record of *where* an answer came from. Every `SourceRecord` in a `FinalResponse` includes the URL, title, and retrieved timestamp. Every `EvidenceRecord` includes the document ID, chunk ID, and relevance score — tracing exactly which chunk of which document contributed to the answer. The Blackboard audit log records which agent wrote which field and when. This means for any answer, you can trace: which agent produced it → which tool it used → what source it retrieved → which chunk it cited.

---

**Q19. How did you verify that A2A communication is genuinely cross-framework?**

The ADK agent and CrewAI agents run as different logical components. The A2A server is a separate FastAPI process that can be started independently (`python -m app.protocols.a2a.server`). The CrewAI `A2ARagTool` uses `httpx` to make a real HTTP request to port 8002. You can verify this by: (1) starting the A2A server in one terminal; (2) running the integration test `test_live_rag_query` which sends a real HTTP request; (3) examining the server logs to see the ADK `LlmAgent` process the request. The test `test_send_task_to_offline_server_returns_error_response` further proves the HTTP boundary — when the server is offline, the client gets a connection error (not a Python exception from a direct function call).

---

**Q20. What are the main limitations of this project?**

1. **Heuristic evaluation** — correctness scores are not validated; human evaluation would strengthen claims
2. **Ephemeral storage on Cloud Run** — FAISS index and SQLite lost on restart; production needs persistent storage
3. **DuckDuckGo rate limits** — free search returns 0 results under heavy load; a paid search API would be more reliable
4. **Single model** — all agents use the same Gemini model; specialised models per agent could improve results
5. **No authentication** — the Streamlit UI is publicly accessible; production needs user auth
6. **Sequential CrewAI execution** — within CrewAI, tasks run sequentially even in the parallel pattern; true async within CrewAI would require the Flow API
7. **Token count approximation** — actual token usage may differ from our estimates
8. **Small document corpus** — evaluation assumed one test PDF; results would differ with a large corpus

---

**Q21. How is the system structured as a final-year project vs a production system?**

| Aspect | Final-Year Project | Production |
|--------|-------------------|-----------|
| Storage | SQLite + local FAISS | PostgreSQL + Vertex AI Vector Search |
| Auth | None | Cloud IAP / OAuth2 |
| Scaling | Single Cloud Run instance | Auto-scaling with min-instances=1 |
| Search | DuckDuckGo (free) | Paid search API (SerpAPI) |
| Monitoring | Structured logs + Streamlit | Cloud Monitoring + Alerting |
| Secrets | .env file | Secret Manager only |
| Cost | Pay-per-request Gemini | Reserved capacity |

---

**Q22. What happens when the LLM returns a malformed or empty response?**

Every agent wraps its LLM call in a `try/except`. If the LLM returns an empty response, the agent logs a warning and returns a structured error result (e.g., `{"answer": "No response from LLM", "success": False}`). The Blackboard records a FAILED event. The Critic sees the empty result and returns `INSUFFICIENT_EVIDENCE`. The Synthesis Agent includes the failure in the `limitations` list of the `FinalResponse`. The workflow always returns a `FinalResponse` object — it never raises an unhandled exception to the user.

---

**Q23. How do you handle the evaluation of security test cases (SEC category)?**

Security test cases (e.g., prompt injection attempts) are expected to be *rejected* by the guardrails before any LLM call. A successful result for a SEC test case is `completion_success=False` AND `verification_status=INSUFFICIENT_EVIDENCE` (rejection) — not a genuine answer. The scoring function detects these by checking if the `reference_answer` field is `"rejected"` and scores them as pass/fail based on whether the guardrail fired correctly, not on answer quality.

---

**Q24. What would you use instead of FAISS for a production RAG system?**

FAISS is an excellent in-process vector similarity library for local/development use. For production:
- **Vertex AI Vector Search** — managed, scalable, integrates with GCP
- **Pinecone** — fully managed, low-latency
- **Chroma** (self-hosted) — open-source, persistent
- **pgvector** — PostgreSQL extension, good if already using Postgres for Blackboard

The `VectorStore` class in `app/storage/vector_store.py` is designed with a clean interface so the FAISS backend can be swapped without changing the RAG Agent code.

---

**Q25. How long does a typical hierarchical workflow run take and why?**

A typical HIERARCHICAL run takes **20–40 seconds** with the current setup. Breakdown:
- Supervisor classification: ~0.5s (heuristic, no LLM)
- Research Agent (web search + LLM): ~8–15s (3–4 DuckDuckGo calls + LLM synthesis)
- A2A RAG call: ~2–5s (FAISS search + LLM) — or instant if no documents indexed
- Synthesis Agent (LLM): ~5–10s
- Critic Agent (LLM): ~3–7s

The PARALLEL pattern saves ~40% of this time by running Research and RAG simultaneously. The main bottleneck is LLM response time (Gemini API latency). DuckDuckGo search reliability also affects total time when rate-limited.

