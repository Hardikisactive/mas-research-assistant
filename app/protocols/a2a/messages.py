"""
Agent-to-Agent (A2A) communication protocol.
Defines typed messages that agents exchange via the LangGraph state.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class MessageType(str, Enum):
    TASK = "task"            # supervisor assigns task
    RESULT = "result"        # agent returns result
    ERROR = "error"          # agent signals error
    CLARIFY = "clarify"      # agent requests clarification
    HEARTBEAT = "heartbeat"  # liveness check


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class A2AMessage(BaseModel):
    """Base message exchanged between agents."""
    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    message_type: MessageType
    sender: str          # agent name
    recipient: str       # agent name or "broadcast"
    priority: Priority = Priority.NORMAL
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = None  # links reply to original task
    session_id: Optional[str] = None

    def reply(self, sender: str, payload: dict, msg_type: MessageType = MessageType.RESULT) -> "A2AMessage":
        """Create a reply to this message."""
        return A2AMessage(
            message_type=msg_type,
            sender=sender,
            recipient=self.sender,
            payload=payload,
            correlation_id=self.message_id,
            session_id=self.session_id,
        )


class TaskMessage(A2AMessage):
    """Supervisor → Agent: assign a research sub-task."""
    message_type: MessageType = MessageType.TASK

    @classmethod
    def create(cls, sender: str, recipient: str, task: str, context: dict = None, session_id: str = None) -> "TaskMessage":
        return cls(
            sender=sender,
            recipient=recipient,
            payload={"task": task, "context": context or {}},
            session_id=session_id,
        )


class ResultMessage(A2AMessage):
    """Agent → Supervisor: return completed task result."""
    message_type: MessageType = MessageType.RESULT

    @classmethod
    def create(cls, sender: str, recipient: str, result: Any, correlation_id: str = None, session_id: str = None) -> "ResultMessage":
        return cls(
            sender=sender,
            recipient=recipient,
            payload={"result": result},
            correlation_id=correlation_id,
            session_id=session_id,
        )

