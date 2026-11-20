"""
A2A Protocol message schemas and Agent Card definition.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.base import _now, _uid


class A2ATaskRequest(BaseModel):
    """Task request sent from CrewAI side to ADK agent via A2A protocol."""
    task_id: str = Field(default_factory=_uid)
    requesting_agent: str
    task_type: str  # "rag_query" | "verification" | etc.
    payload: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 60
    created_at: datetime = Field(default_factory=_now)


class A2ATaskResponse(BaseModel):
    """Response from ADK agent back to CrewAI side via A2A protocol."""
    task_id: str
    responding_agent: str
    status: str  # "success" | "error" | "timeout"
    result: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    duration_ms: float = 0.0
    created_at: datetime = Field(default_factory=_now)


class AgentCard(BaseModel):
    """Agent capability metadata — required by A2A for agent discovery."""
    agent_id: str = Field(default_factory=_uid)
    name: str
    framework: str  # "crewai" | "google-adk"
    capabilities: list[str] = Field(default_factory=list)
    endpoint: str
    version: str = "1.0"
    description: str = ""
