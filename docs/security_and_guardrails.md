# Security and Guardrails

## Threat Model

The system processes user-supplied text queries, uploaded documents, and CSV files, then calls external LLMs and search tools. The primary threats are:

| Threat | Vector | Mitigation |
|--------|--------|-----------|
| Prompt injection | User query | Pattern detection + sanitization |
| Jailbreak attempts | User query | Keyword blocklist |
| Path traversal | File uploads / CSV paths | Path validation against allowed directories |
| Oversized input | Query / file | Length limits enforced before processing |
| Malicious file content | PDF/CSV upload | Type validation, size limit, hash logging |
| Injection via retrieved content | RAG chunks, web snippets | Content validation + truncation |
| Unsafe tool execution | Data analysis queries | Allowlisted pandas operations only — no `eval()` |
| Secret leakage | Log output | Key redaction in all log formatters |

---

## Layer 1: Input Guardrails

**File:** `app/security/guardrails.py`  
**Tests:** `tests/unit/test_guardrails.py` (37 tests), `tests/security/test_injection.py` (26 tests)

### Query Validation (`validate_query`)

Every query passes through `validate_query()` before any agent sees it.

**Checks performed:**
1. **Empty / whitespace-only** — rejected immediately
2. **Length limit** — configurable via `MAX_QUERY_LENGTH` (default 2000 chars)
3. **Null bytes** (`\x00`) — rejected (common in binary injection attacks)
4. **Control characters** (`\x01`–`\x08`, `\x0b`–`\x1f`) — rejected
5. **Prompt injection patterns** — regex match against blocklist
6. **Whitespace normalisation** — multiple spaces/newlines collapsed

```python
from app.security.guardrails import validate_query, GuardrailViolation

try:
    sanitized, warnings = validate_query(raw_query, max_length=2000)
except GuardrailViolation as e:
    print(e.violation_type)   # "empty_query" | "too_long" | "injection" | etc.
    print(str(e))             # human-readable message
```

### Injection Pattern Blocklist

The following patterns are matched case-insensitively (regex):

```
ignore previous instructions
ignore all prior instructions
forget your (guidelines|training|instructions)
you are now (an? )?(ai|assistant|bot|gpt|llm)
new instruction[s]?:
enable .{0,20} mode
(jailbreak|bypass|override).{0,30}(safety|filter|rule|guideline)
reveal (the|your) (system prompt|secret|instructions)
\{\{.*\}\}    # template injection {{ var }}
<script       # HTML/JS injection
```

Academic queries about these topics (e.g., "explain how prompt injection works") are **not** blocked — only queries that *are* injection attempts.

---

## Layer 2: File Upload Validation

**File:** `app/security/guardrails.py` — `validate_file_upload()`  
**Also:** `app/security/validators.py` — `validate_csv_path()`

### File Upload Checks

| Check | Detail |
|-------|--------|
| **File type** | Only `.pdf`, `.txt`, `.docx`, `.json`, `.csv` accepted |
| **File size** | Max 50 MB (configurable via `MAX_FILE_SIZE_MB`) |
| **Path traversal** | Filename sanitized — no `..`, no absolute paths, no null bytes |
| **Content hash** | SHA-256 logged for audit trail |

```python
from app.security.guardrails import validate_file_upload

safe_path, file_hash = validate_file_upload(
    file_path="data/uploads/report.pdf",
    filename="report.pdf",
    max_size_mb=50,
)
```

### CSV Path Traversal Protection

```python
from app.security.validators import validate_csv_path

# Raises ValueError if path escapes data/uploads/
safe = validate_csv_path("data/uploads/fire_data.csv")

# These all raise:
validate_csv_path("../../etc/passwd")      # path traversal
validate_csv_path("/etc/passwd")           # absolute path
validate_csv_path("data/uploads/x.exe")   # wrong extension
```

---

## Layer 3: Retrieved Content Validation

**File:** `app/security/guardrails.py` — `validate_retrieved_content()`

Web search snippets and RAG chunks pass through content validation before being included in agent context.

**Checks:**
1. **Truncation** — Content > 50,000 chars is truncated (prevents context flooding)
2. **Injection scan** — Checks for injection patterns in retrieved content
3. **Source tagging** — Each piece of content is tagged with its source URL/ID

If injection patterns are found in retrieved content, the content is **not rejected** (that would break legitimate research) but a warning flag is set and the content is noted in the audit log. The system does not execute or act on instructions found in retrieved content.

```python
from app.security.guardrails import validate_retrieved_content

safe_content, warnings = validate_retrieved_content(
    content=raw_snippet,
    source="https://example.com/article",
    max_length=50000,
)
```

---

## Layer 4: Tool Output Validation

**File:** `app/security/guardrails.py` — `validate_tool_output()`

Before tool results are inserted into agent context:
1. **Type check** — output must be a string or JSON-serialisable dict
2. **Length truncation** — capped at 10,000 chars
3. **Malformed JSON detection** — partial JSON is completed or stripped

---

## Layer 5: Data Analysis Sandboxing

**File:** `app/agents/data_analysis/agent.py` — `DataAnalysisTool`  
**Also:** `app/security/validators.py` — `validate_expression()`

The Data Analysis Agent accepts analysis queries but **does not execute arbitrary Python or shell commands**. Instead, it supports an allowlisted set of operations:

| Operation | pandas equivalent | Allowed |
|-----------|------------------|---------|
| `describe` | `df.describe()` | ✅ |
| `head` | `df.head(10)` | ✅ |
| `dtypes` | `df.dtypes` | ✅ |
| `missing` | `df.isnull().sum()` | ✅ |
| `corr` | `df.corr()` | ✅ |
| `value_counts` | `df[col].value_counts()` | ✅ |
| `shape` | `df.shape` | ✅ |
| Arbitrary Python `eval()` | any | ❌ |
| Shell commands | `os.system`, `subprocess` | ❌ |
| File writes | `df.to_csv(...)` | ❌ |

The calculator tool uses `validate_expression()` which restricts `eval()` to pure arithmetic (numbers, operators, `math.*` functions) — no imports, no attribute access, no function definitions.

```python
from app.security.validators import validate_expression

validate_expression("2 + 3 * sqrt(16)")   # OK → 14.0
validate_expression("import os")          # raises ValueError
validate_expression("__import__('os')")   # raises ValueError
```

---

## Layer 6: URL Validation

**File:** `app/security/guardrails.py` — `validate_url()`

Before any URL from search results is stored or presented:
1. Must start with `http://` or `https://`
2. Must have a valid netloc (domain)
3. Internal/private IP ranges are rejected
4. Localhost URLs are rejected

---

## Layer 7: Output Sanitization

**File:** `app/security/validators.py` — `sanitize_html()`

When rendering agent outputs in the Streamlit UI, HTML is escaped to prevent XSS. Markdown is rendered via Streamlit's safe renderer.

---

## Secret Handling

- All API keys are loaded **exclusively from `.env`** (never hardcoded)
- The structured logger redacts values matching key patterns (see `app/observability/logger.py`)
- `.env` is in `.gitignore` — never committed
- Cloud Run deployment uses **Secret Manager**, not env vars in the container definition

---

## GuardrailViolation Exception

```python
class GuardrailViolation(Exception):
    def __init__(self, message: str, violation_type: str):
        self.violation_type = violation_type
        # violation_type values:
        # "empty_query" | "too_long" | "control_chars" |
        # "null_bytes"  | "injection" | "invalid_file_type" |
        # "file_too_large" | "path_traversal"
```

When a `GuardrailViolation` is raised, the workflow engine catches it immediately, creates a REJECTED Blackboard entry, and returns a `FinalResponse` with `is_mock=False` and a user-facing explanation — without calling any LLM.

---

## Test Coverage

| Test File | Tests | What is Covered |
|-----------|-------|----------------|
| `tests/unit/test_guardrails.py` | 37 | validate_query (valid + rejected + injection), file upload, URL, content validation |
| `tests/security/test_injection.py` | 26 | 10 injection payloads caught, 10 legitimate queries pass, content validation edge cases |

Run:
```powershell
cd e:\PRJ-4\mas_project
python -m pytest tests/unit/test_guardrails.py tests/security/test_injection.py -v
```

