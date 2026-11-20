"""
Observability: Structured JSON logger with run_id/agent context.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional


class StructuredFormatter(logging.Formatter):
    """Emit JSON log lines for structured observability."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach extra fields
        for key in ("run_id", "agent", "tool", "event_type"):
            if hasattr(record, key):
                log_obj[key] = getattr(record, key)
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger with structured JSON handler."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # JSON handler to stdout (captured by Cloud Run / container logs)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())

    # Remove default handlers, add ours
    root.handlers.clear()
    root.addHandler(handler)

    # Silence noisy libraries
    for lib in ["httpx", "httpcore", "urllib3", "sentence_transformers"]:
        logging.getLogger(lib).setLevel(logging.WARNING)


def get_agent_logger(agent_name: str, run_id: Optional[str] = None) -> logging.LoggerAdapter:
    """Return a LoggerAdapter that tags every log with agent name and run_id."""
    base_logger = logging.getLogger(f"mas.agent.{agent_name}")
    extra = {"agent": agent_name}
    if run_id:
        extra["run_id"] = run_id
    return logging.LoggerAdapter(base_logger, extra)
