"""
Observability: in-process metrics collector.
Stores per-run timing, cost, and agent event summaries.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Optional


class MetricsCollector:
    """Thread-safe metrics collector. One instance per process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, dict] = {}

    def start_run(self, run_id: str, pattern: str, query: str) -> None:
        with self._lock:
            self._runs[run_id] = {
                "run_id": run_id,
                "pattern": pattern,
                "query": query[:100],
                "start_time": time.monotonic(),
                "end_time": None,
                "agents": defaultdict(lambda: {"calls": 0, "errors": 0,
                                               "total_ms": 0.0}),
                "tools": defaultdict(lambda: {"calls": 0, "errors": 0,
                                              "total_ms": 0.0}),
                "a2a_calls": 0,
                "a2a_errors": 0,
                "retries": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0.0,
            }

    def record_agent(
        self,
        run_id: str,
        agent_name: str,
        duration_ms: float,
        error: bool = False,
    ) -> None:
        with self._lock:
            if run_id not in self._runs:
                return
            a = self._runs[run_id]["agents"][agent_name]
            a["calls"] += 1
            a["total_ms"] += duration_ms
            if error:
                a["errors"] += 1

    def record_tool(
        self,
        run_id: str,
        tool_name: str,
        duration_ms: float,
        error: bool = False,
    ) -> None:
        with self._lock:
            if run_id not in self._runs:
                return
            t = self._runs[run_id]["tools"][tool_name]
            t["calls"] += 1
            t["total_ms"] += duration_ms
            if error:
                t["errors"] += 1

    def record_a2a(self, run_id: str, success: bool) -> None:
        with self._lock:
            if run_id not in self._runs:
                return
            self._runs[run_id]["a2a_calls"] += 1
            if not success:
                self._runs[run_id]["a2a_errors"] += 1

    def record_tokens(
        self, run_id: str, input_tokens: int, output_tokens: int, cost_usd: float
    ) -> None:
        with self._lock:
            if run_id not in self._runs:
                return
            r = self._runs[run_id]
            r["input_tokens"] += input_tokens
            r["output_tokens"] += output_tokens
            r["estimated_cost_usd"] += cost_usd

    def finish_run(self, run_id: str) -> Optional[dict]:
        with self._lock:
            if run_id not in self._runs:
                return None
            r = self._runs[run_id]
            r["end_time"] = time.monotonic()
            r["total_ms"] = (r["end_time"] - r["start_time"]) * 1000
            return dict(r)

    def get_run(self, run_id: str) -> Optional[dict]:
        with self._lock:
            return dict(self._runs.get(run_id, {}))

    def list_runs(self) -> list[dict]:
        with self._lock:
            return [dict(v) for v in self._runs.values()]


# Singleton
_collector: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector
