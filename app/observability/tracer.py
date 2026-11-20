"""
Lightweight tracing for agent pipeline steps.
Provides a Tracer that records spans with timing and metadata.
If OpenTelemetry is available and configured, spans are also exported.
"""
import time
import uuid
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional, Generator
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class Span:
    name: str
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    trace_id: str = ""
    parent_id: Optional[str] = None
    start_time: float = field(default_factory=time.perf_counter)
    end_time: Optional[float] = None
    attributes: dict = field(default_factory=dict)
    status: str = "OK"
    error: Optional[str] = None

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def finish(self, error: Optional[str] = None) -> None:
        self.end_time = time.perf_counter()
        if error:
            self.status = "ERROR"
            self.error = error

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error": self.error,
            "attributes": self.attributes,
        }


class Tracer:
    """
    Simple in-process tracer. One Tracer instance per request/session.
    """
    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or uuid.uuid4().hex
        self._spans: list[Span] = []
        self._active: list[Span] = []

    @contextmanager
    def span(self, name: str, attributes: Optional[dict] = None) -> Generator[Span, None, None]:
        """Context manager that records a span."""
        parent_id = self._active[-1].span_id if self._active else None
        sp = Span(
            name=name,
            trace_id=self.trace_id,
            parent_id=parent_id,
            attributes=attributes or {},
        )
        self._active.append(sp)
        self._spans.append(sp)
        try:
            yield sp
            sp.finish()
        except Exception as exc:
            sp.finish(error=str(exc))
            raise
        finally:
            if sp in self._active:
                self._active.remove(sp)
        logger.debug("span", extra=sp.to_dict())

    def get_trace(self) -> list[dict]:
        return [s.to_dict() for s in self._spans]

    def summary(self) -> dict:
        total = sum((s.duration_ms or 0) for s in self._spans if s.parent_id is None)
        errors = [s.name for s in self._spans if s.status == "ERROR"]
        return {
            "trace_id": self.trace_id,
            "span_count": len(self._spans),
            "total_duration_ms": round(total, 2),
            "errors": errors,
        }

