"""
Blackboard — Shared State Architecture using SQLite with WAL mode.

The Blackboard is the single source of truth for workflow state.
Every agent reads from and writes to the Blackboard, making the full
run history auditable and reproducible.

Thread-safety: All writes use a threading.Lock() and SQLite transactions.
:memory: support: uses a single persistent connection for in-memory DBs.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ─── DDL ───────────────────────────────────────────────────────────────────────

_DDL_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,
    conversation_id TEXT,
    original_query  TEXT NOT NULL,
    sanitized_query TEXT DEFAULT '',
    persona         TEXT DEFAULT 'RESEARCHER',
    workflow_pattern TEXT DEFAULT 'HIERARCHICAL',
    plan            TEXT DEFAULT '{}',
    current_status  TEXT DEFAULT 'PENDING',
    selected_agents TEXT DEFAULT '[]',
    agent_tasks     TEXT DEFAULT '{}',
    agent_outputs   TEXT DEFAULT '{}',
    tool_results    TEXT DEFAULT '[]',
    retrieved_documents TEXT DEFAULT '[]',
    evidence_records    TEXT DEFAULT '[]',
    critic_results      TEXT DEFAULT '{}',
    retry_count     INTEGER DEFAULT 0,
    errors          TEXT DEFAULT '[]',
    timing_metrics  TEXT DEFAULT '{}',
    cost_metrics    TEXT DEFAULT '{}',
    final_output    TEXT DEFAULT NULL,
    version         INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
"""

_DDL_EVENTS = """
CREATE TABLE IF NOT EXISTS agent_events (
    event_id    TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    agent_name  TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    duration_ms REAL,
    status      TEXT NOT NULL DEFAULT 'PENDING',
    summary     TEXT DEFAULT '',
    error       TEXT
)
"""

_DDL_TOOL_CALLS = """
CREATE TABLE IF NOT EXISTS tool_calls (
    tool_call_id TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    tool_name    TEXT NOT NULL,
    agent_name   TEXT NOT NULL,
    input_summary  TEXT DEFAULT '',
    output_summary TEXT,
    success      INTEGER DEFAULT 1,
    duration_ms  REAL DEFAULT 0.0,
    error        TEXT,
    timestamp    TEXT NOT NULL
)
"""

_DDL_AUDIT = """
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id    TEXT PRIMARY KEY,
    run_id      TEXT,
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    field_name  TEXT,
    old_version INTEGER,
    new_version INTEGER,
    timestamp   TEXT NOT NULL,
    details     TEXT
)
"""

_LIST_FIELDS = {
    "selected_agents", "tool_results", "retrieved_documents",
    "evidence_records", "errors",
}
_DICT_FIELDS = {
    "plan", "agent_tasks", "agent_outputs", "critic_results",
    "timing_metrics", "cost_metrics",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


class Blackboard:
    """
    SQLite-backed Blackboard providing shared state for all agents.

    Usage:
        bb = Blackboard("data/blackboard.db")
        run_id = bb.create_run("What is quantum computing?", "RESEARCHER")
        bb.update_field(run_id, "current_status", "RUNNING", "supervisor")
        state = bb.get_run(run_id)
    """

    def __init__(self, db_path: str = "data/blackboard.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._is_memory = (db_path == ":memory:")

        if not self._is_memory:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # For :memory: keep a single persistent connection
        if self._is_memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys=ON")
        else:
            self._conn = None

        self._init_db()
        logger.info(f"Blackboard initialised at {db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        """Return connection — persisted for :memory:, new for file."""
        if self._is_memory:
            return self._conn
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _exec(self, sql: str, params: tuple = ()) -> list:
        """Execute a read query and return rows as dicts."""
        conn = self._get_conn()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            if not self._is_memory:
                conn.close()

    def _write(self, ops: list[tuple]) -> None:
        """Execute one or more write statements in a single transaction."""
        conn = self._get_conn()
        try:
            for sql, params in ops:
                conn.execute(sql, params)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if not self._is_memory:
                conn.close()

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._lock:
            self._write([
                (_DDL_RUNS, ()),
                (_DDL_EVENTS, ()),
                (_DDL_TOOL_CALLS, ()),
                (_DDL_AUDIT, ()),
            ])

    # ─── Run Management ──────────────────────────────────────────────

    def create_run(
        self,
        original_query: str,
        persona: str = "RESEARCHER",
        workflow_pattern: str = "HIERARCHICAL",
        conversation_id: Optional[str] = None,
    ) -> str:
        run_id = _new_id()
        now = _now_iso()
        with self._lock:
            self._write([(
                """INSERT INTO runs
                   (run_id, conversation_id, original_query, persona,
                    workflow_pattern, current_status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'PENDING', ?, ?)""",
                (run_id, conversation_id, original_query, persona,
                 workflow_pattern, now, now),
            )])
        self._audit(run_id, "create_run", "system",
                    details=f"persona={persona} pattern={workflow_pattern}")
        logger.info(f"Blackboard: created run {run_id}")
        return run_id

    def get_run(self, run_id: str) -> Optional[dict]:
        rows = self._exec("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if not rows:
            return None
        result = rows[0]
        for field in list(_LIST_FIELDS) + list(_DICT_FIELDS) + ["final_output"]:
            if result.get(field) is not None:
                try:
                    result[field] = json.loads(result[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result

    def update_field(
        self,
        run_id: str,
        field_name: str,
        value: Any,
        updated_by: str,
    ) -> bool:
        allowed_fields = {
            "sanitized_query", "plan", "current_status", "selected_agents",
            "agent_tasks", "agent_outputs", "tool_results", "retrieved_documents",
            "evidence_records", "critic_results", "retry_count", "errors",
            "timing_metrics", "cost_metrics", "final_output",
        }
        if field_name not in allowed_fields:
            logger.error(f"Blackboard: rejected update to disallowed field '{field_name}'")
            return False

        serialized = json.dumps(value) if isinstance(value, (dict, list)) else value
        with self._lock:
            rows = self._exec("SELECT version FROM runs WHERE run_id = ?", (run_id,))
            if not rows:
                return False
            old_version = rows[0]["version"]
            new_version = old_version + 1
            self._write([(
                f"UPDATE runs SET {field_name} = ?, version = ?, "
                f"updated_at = ? WHERE run_id = ? AND version = ?",
                (serialized, new_version, _now_iso(), run_id, old_version),
            )])
        self._audit(run_id, "update_field", updated_by,
                    field_name=field_name,
                    old_version=old_version, new_version=new_version)
        return True

    def append_to_list_field(
        self,
        run_id: str,
        field_name: str,
        item: Any,
        updated_by: str,
    ) -> bool:
        if field_name not in _LIST_FIELDS:
            logger.error(f"Blackboard: '{field_name}' is not a list field")
            return False
        with self._lock:
            rows = self._exec(
                f"SELECT {field_name}, version FROM runs WHERE run_id = ?", (run_id,)
            )
            if not rows:
                return False
            current_list = json.loads(rows[0][field_name] or "[]")
            current_list.append(item)
            new_version = rows[0]["version"] + 1
            self._write([(
                f"UPDATE runs SET {field_name} = ?, version = ?, updated_at = ? "
                f"WHERE run_id = ? AND version = ?",
                (json.dumps(current_list), new_version, _now_iso(),
                 run_id, rows[0]["version"]),
            )])
        self._audit(run_id, "append_list", updated_by, field_name=field_name)
        return True

    def update_dict_field(
        self,
        run_id: str,
        field_name: str,
        key: str,
        value: Any,
        updated_by: str,
    ) -> bool:
        if field_name not in _DICT_FIELDS:
            logger.error(f"Blackboard: '{field_name}' is not a dict field")
            return False
        with self._lock:
            rows = self._exec(
                f"SELECT {field_name}, version FROM runs WHERE run_id = ?", (run_id,)
            )
            if not rows:
                return False
            current_dict = json.loads(rows[0][field_name] or "{}")
            current_dict[key] = value
            new_version = rows[0]["version"] + 1
            self._write([(
                f"UPDATE runs SET {field_name} = ?, version = ?, updated_at = ? "
                f"WHERE run_id = ? AND version = ?",
                (json.dumps(current_dict), new_version, _now_iso(),
                 run_id, rows[0]["version"]),
            )])
        self._audit(run_id, "update_dict", updated_by, field_name=f"{field_name}.{key}")
        return True

    # ─── Events and Tools ────────────────────────────────────────────

    def record_event(
        self,
        run_id: str,
        agent_name: str,
        event_type: str,
        status: str,
        summary: str,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
    ) -> str:
        event_id = _new_id()
        with self._lock:
            self._write([(
                """INSERT INTO agent_events
                   (event_id, run_id, agent_name, event_type, timestamp,
                    duration_ms, status, summary, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, run_id, agent_name, event_type, _now_iso(),
                 duration_ms, status, summary, error),
            )])
        return event_id

    def record_tool_call(
        self,
        run_id: str,
        tool_name: str,
        agent_name: str,
        input_summary: str,
        output_summary: Optional[str],
        success: bool,
        duration_ms: float,
        error: Optional[str] = None,
    ) -> str:
        tc_id = _new_id()
        with self._lock:
            self._write([(
                """INSERT INTO tool_calls
                   (tool_call_id, run_id, tool_name, agent_name,
                    input_summary, output_summary, success, duration_ms,
                    error, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tc_id, run_id, tool_name, agent_name, input_summary,
                 output_summary, 1 if success else 0, duration_ms,
                 error, _now_iso()),
            )])
        return tc_id

    # ─── Queries ─────────────────────────────────────────────────────

    def get_events(self, run_id: str) -> list[dict]:
        return self._exec(
            "SELECT * FROM agent_events WHERE run_id = ? ORDER BY timestamp",
            (run_id,),
        )

    def get_tool_calls(self, run_id: str) -> list[dict]:
        return self._exec(
            "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY timestamp",
            (run_id,),
        )

    def list_runs(self, limit: int = 100) -> list[dict]:
        return self._exec(
            """SELECT run_id, persona, workflow_pattern, current_status,
                      original_query, created_at, updated_at, retry_count
               FROM runs ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )

    def get_audit_log(self, run_id: Optional[str] = None, limit: int = 200) -> list[dict]:
        if run_id:
            return self._exec(
                "SELECT * FROM audit_log WHERE run_id = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (run_id, limit),
            )
        return self._exec(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )

    # ─── Audit ───────────────────────────────────────────────────────

    def _audit(
        self,
        run_id: Optional[str],
        action: str,
        actor: str,
        field_name: Optional[str] = None,
        old_version: Optional[int] = None,
        new_version: Optional[int] = None,
        details: Optional[str] = None,
    ) -> None:
        try:
            self._write([(
                """INSERT INTO audit_log
                   (audit_id, run_id, action, actor, field_name,
                    old_version, new_version, timestamp, details)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_new_id(), run_id, action, actor, field_name,
                 old_version, new_version, _now_iso(), details),
            )])
        except Exception as exc:
            logger.warning(f"Audit log write failed (non-fatal): {exc}")


# ─── Singleton ───────────────────────────────────────────────────────────────

_blackboard: Optional[Blackboard] = None


def get_blackboard(db_path: Optional[str] = None) -> Blackboard:
    global _blackboard
    if _blackboard is None:
        from app.config.settings import get_settings
        path = db_path or get_settings().blackboard_db_path
        _blackboard = Blackboard(path)
    return _blackboard
