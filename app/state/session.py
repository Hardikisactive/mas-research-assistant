"""
Session state management for multi-turn research conversations.
"""
import uuid
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class SessionTurn:
    """A single user-assistant exchange."""
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user_query: str = ""
    assistant_response: str = ""
    sources: list = field(default_factory=list)
    agent_trace: list = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: float = 0.0
    error: Optional[str] = None


@dataclass
class Session:
    """A research session with full conversation history."""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    turns: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def add_turn(self, turn: SessionTurn) -> None:
        self.turns.append(turn)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def get_history_text(self, max_turns: int = 5) -> str:
        """Return recent conversation history as a text block for LLM context."""
        recent = self.turns[-max_turns:]
        parts = []
        for t in recent:
            parts.append(f"User: {t.user_query}")
            if t.assistant_response:
                parts.append(f"Assistant: {t.assistant_response}")
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return asdict(self)


class SessionStore:
    """Thread-safe in-memory session store with optional disk persistence."""

    def __init__(self, persist_dir: Optional[Path] = None):
        self._sessions: dict[str, Session] = {}
        self._lock = RLock()
        self._persist_dir = persist_dir
        if persist_dir:
            persist_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, metadata: dict = None) -> Session:
        session = Session(metadata=metadata or {})
        with self._lock:
            self._sessions[session.session_id] = session
        logger.info(f"Session created: {session.session_id}")
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None and self._persist_dir:
            session = self._load_from_disk(session_id)
        return session

    def get_or_create(self, session_id: Optional[str] = None) -> Session:
        if session_id:
            session = self.get_session(session_id)
            if session:
                return session
        return self.create_session()

    def add_turn(self, session_id: str, turn: SessionTurn) -> None:
        session = self.get_or_create(session_id)
        session.add_turn(turn)
        if self._persist_dir:
            self._save_to_disk(session)

    def list_sessions(self) -> list:
        with self._lock:
            return list(self._sessions.keys())

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            existed = session_id in self._sessions
            self._sessions.pop(session_id, None)
        if existed and self._persist_dir:
            path = self._persist_dir / f"{session_id}.json"
            path.unlink(missing_ok=True)
        return existed

    def _save_to_disk(self, session: Session) -> None:
        path = self._persist_dir / f"{session.session_id}.json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist session {session.session_id}: {e}")

    def _load_from_disk(self, session_id: str) -> Optional[Session]:
        path = self._persist_dir / f"{session_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            session = Session(
                session_id=data["session_id"],
                created_at=data["created_at"],
                updated_at=data["updated_at"],
                metadata=data.get("metadata", {}),
                turns=[SessionTurn(**t) for t in data.get("turns", [])],
            )
            with self._lock:
                self._sessions[session_id] = session
            return session
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None


_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore(persist_dir=Path("data/sessions"))
    return _store
