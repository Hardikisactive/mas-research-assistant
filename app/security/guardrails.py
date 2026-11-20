"""
Layered security guardrails for input validation, prompt injection detection,
output validation, and file safety checks.
"""
import re
import logging
from typing import Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

# Injection patterns - common prompt injection signatures
INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"ignore all (previous|prior|above) (instructions|prompts)",
    r"you are now",
    r"forget your (instructions|training|guidelines|system prompt)",
    r"disregard (your|all) (instructions|training|rules|guidelines)",
    r"new instruction:",
    r"system prompt:",
    r"reveal (your|the) (system|hidden|secret) (prompt|instructions|key|api|system)",
    r"reveal (your|the) (system|hidden|secret) (prompt|system prompt)",
    r"reveal .{0,20}(system prompt|api key|secret key)",
    r"print (your|the) (instructions|system prompt|api key)",
    r"what (is|are) (your|the) (instructions|system prompt|api key|secret)",
    r"override (your|the|all) (instructions|rules|guidelines|safety)",
    r"jailbreak",
    r"dan mode",
    r"developer mode",
    r"act as (if you are|a|an) (?!researcher|student)",  # allow legitimate roles
    r"\[INST\]",  # Llama injection markers
    r"<\|system\|>",
    r"<\|user\|>",
    r"\{\{.*\}\}",  # template injection
]

TOXIC_PATTERNS = [
    r"\b(suicide|self.harm|self-harm)\b.*method",
    r"how to (make|build|create|synthesize) (a bomb|explosives|bioweapon|nerve agent)",
    r"(generate|write|create) (malware|ransomware|exploit code)",
    r"how to (hack|bypass|break into) (a|the|someone)",
]

COMPILED_INJECTION = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
COMPILED_TOXIC = [re.compile(p, re.IGNORECASE) for p in TOXIC_PATTERNS]

ALLOWED_FILE_EXTENSIONS = {'.pdf', '.txt', '.docx', '.csv', '.json', '.md'}
MAX_FILENAME_LENGTH = 255


class GuardrailViolation(Exception):
    """Raised when a guardrail check fails."""
    def __init__(self, message: str, violation_type: str):
        super().__init__(message)
        self.violation_type = violation_type


def validate_query(query: str, max_length: int = 2000) -> Tuple[str, list]:
    """
    Validate and sanitize a user query.
    Returns: (sanitized_query, list_of_warnings)
    Raises: GuardrailViolation if query must be rejected.
    """
    warnings = []

    if not query or not query.strip():
        raise GuardrailViolation("Empty query", "EMPTY_INPUT")

    query = query.strip()

    if len(query) > max_length:
        raise GuardrailViolation(
            f"Query exceeds maximum length of {max_length} characters",
            "INPUT_TOO_LONG"
        )

    # Check for null bytes and control characters (except normal whitespace)
    if any(ord(c) < 32 and c not in '\n\r\t' for c in query):
        raise GuardrailViolation("Query contains invalid control characters", "INVALID_CHARS")

    # Check for prompt injection
    for pattern in COMPILED_INJECTION:
        if pattern.search(query):
            logger.warning(f"Potential prompt injection detected: pattern={pattern.pattern[:50]}")
            raise GuardrailViolation(
                "Query appears to contain instructions that attempt to override system behavior.",
                "PROMPT_INJECTION"
            )

    # Check for clearly toxic content
    for pattern in COMPILED_TOXIC:
        if pattern.search(query):
            logger.warning("Toxic content pattern detected in query")
            raise GuardrailViolation(
                "Query contains content that cannot be processed.",
                "TOXIC_CONTENT"
            )

    # Sanitize: normalize whitespace
    sanitized = ' '.join(query.split())

    return sanitized, warnings


def validate_retrieved_content(content: str, source: str = "retrieved") -> Tuple[str, bool]:
    """
    Validate content from untrusted sources (web search, documents, tool outputs).
    Returns: (sanitized_content, has_injection_attempt)
    NOTE: Does NOT raise - logs and returns flag instead.
    """
    has_injection = False

    for pattern in COMPILED_INJECTION:
        if pattern.search(content):
            logger.warning(f"Injection pattern found in {source} content — treating as data, not instruction")
            has_injection = True
            break

    # Truncate extremely long content
    MAX_RETRIEVED = 50_000
    if len(content) > MAX_RETRIEVED:
        content = content[:MAX_RETRIEVED] + "\n[Content truncated for safety]"

    return content, has_injection


def validate_file_upload(filename: str, file_size_bytes: int, max_size_mb: float = 50.0) -> Tuple[str, str]:
    """
    Validate an uploaded file.
    Returns: (safe_filename, detected_type)
    Raises: GuardrailViolation on failure.
    """
    if not filename or not filename.strip():
        raise GuardrailViolation("Empty filename", "INVALID_FILENAME")

    # Sanitize filename - prevent path traversal
    safe_name = Path(filename).name  # strips directory components
    safe_name = re.sub(r'[^\w\.\-]', '_', safe_name)  # allow only safe chars

    if len(safe_name) > MAX_FILENAME_LENGTH:
        raise GuardrailViolation("Filename too long", "FILENAME_TOO_LONG")

    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_FILE_EXTENSIONS:
        raise GuardrailViolation(
            f"File type '{suffix}' not allowed. Supported: {ALLOWED_FILE_EXTENSIONS}",
            "INVALID_FILE_TYPE"
        )

    max_bytes = max_size_mb * 1024 * 1024
    if file_size_bytes > max_bytes:
        raise GuardrailViolation(
            f"File size {file_size_bytes/1024/1024:.1f}MB exceeds limit of {max_size_mb}MB",
            "FILE_TOO_LARGE"
        )

    return safe_name, suffix[1:]  # return (safe_filename, type_without_dot)


def validate_tool_output(tool_name: str, output: dict) -> Tuple[dict, list]:
    """
    Validate tool output structure and content.
    Returns: (validated_output, warnings)
    """
    warnings = []

    if not isinstance(output, dict):
        warnings.append(f"Tool {tool_name} returned non-dict output")
        return {"error": "malformed_output", "raw": str(output)[:500]}, warnings

    # Check for injection in string values
    for key, val in output.items():
        if isinstance(val, str):
            _, has_injection = validate_retrieved_content(val, source=f"tool:{tool_name}:{key}")
            if has_injection:
                warnings.append(f"Injection pattern in tool output field '{key}' — treated as data")

    return output, warnings


def validate_url(url: str) -> bool:
    """Basic URL validation — rejects javascript: and data: URIs."""
    if not url:
        return False
    url_lower = url.lower().strip()
    blocked_schemes = ['javascript:', 'data:', 'vbscript:', 'file:']
    return not any(url_lower.startswith(s) for s in blocked_schemes)
