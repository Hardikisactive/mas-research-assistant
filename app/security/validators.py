"""
Additional validators for MCP tools and API inputs.
"""
import html
import re
from pathlib import Path


def validate_csv_path(path: str, allowed_dir: str) -> Path:
    """
    Validate that *path* resolves within *allowed_dir* (prevents path traversal).

    Returns the resolved Path on success.
    Raises ValueError on traversal attempt or if file doesn't exist.
    """
    allowed = Path(allowed_dir).resolve()
    target = (allowed / Path(path).name).resolve()

    # Ensure resolved path is still inside allowed_dir
    try:
        target.relative_to(allowed)
    except ValueError:
        raise ValueError(f"Path traversal detected: '{path}' escapes allowed directory")

    if not target.exists():
        raise ValueError(f"File not found: {target}")

    return target


def validate_k_parameter(k: int, min_k: int = 1, max_k: int = 20) -> int:
    """
    Clamp *k* to [min_k, max_k] and validate it is an integer.

    Returns the clamped value; raises TypeError if k is not an int.
    """
    if not isinstance(k, int):
        raise TypeError(f"k must be an integer, got {type(k).__name__}")
    return max(min_k, min(max_k, k))


def validate_expression(expr: str, max_len: int = 200) -> str:
    """
    Validate a calculator expression for use with the restricted eval.

    - Must be non-empty.
    - Must not exceed max_len characters.
    - Must not contain obviously dangerous tokens (__import__, exec, eval, open, os).

    Returns the stripped expression on success; raises ValueError on rejection.
    """
    if not expr or not expr.strip():
        raise ValueError("Expression must not be empty")

    expr = expr.strip()

    if len(expr) > max_len:
        raise ValueError(f"Expression exceeds maximum length of {max_len} characters")

    # Blocklist dangerous identifiers even before restricted eval catches them
    dangerous = re.compile(
        r'\b(__import__|exec|eval|open|compile|globals|locals|vars|getattr|setattr|delattr)\b'
    )
    if dangerous.search(expr):
        raise ValueError("Expression contains disallowed identifiers")

    return expr


def sanitize_html(text: str) -> str:
    """
    Simple HTML escape for safe display in web contexts.

    Replaces <, >, &, \", ' with their HTML entity equivalents.
    """
    return html.escape(text, quote=True)

