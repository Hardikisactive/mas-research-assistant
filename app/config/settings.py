"""
Centralised application settings — loaded from .env / environment variables.
All secrets must be in environment variables, NEVER hardcoded.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────
    app_name: str = "MAS Research Assistant"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    log_agent_outputs: bool = True
    redact_sensitive_logs: bool = True

    # ── LLM Providers ────────────────────────────────────────────────
    # Gemini is the primary provider (used for both CrewAI and ADK)
    google_api_key: Optional[str] = Field(default=None, alias="GOOGLE_API_KEY")

    # Optional alternatives
    groq_api_key: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")

    # CrewAI LLM — uses LiteLLM model string format
    # Change CREWAI_LLM_MODEL in .env to switch models
    crewai_llm_model: str = "gemini/gemini-3.1-flash-lite"

    # ADK model string (passed directly to google.adk)
    # Change ADK_MODEL in .env to switch models
    adk_model: str = "gemini-3.1-flash-lite"

    # ── Search ───────────────────────────────────────────────────────
    serpapi_key: Optional[str] = Field(default=None, alias="SERPAPI_KEY")
    duckduckgo_enabled: bool = True
    search_max_results: int = 5

    # ── RAG ──────────────────────────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_top_k: int = 5
    max_file_size_mb: float = 50.0

    # ── Blackboard (SQLite) ──────────────────────────────────────────
    blackboard_db_path: str = "data/blackboard.db"

    # ── A2A ──────────────────────────────────────────────────────────
    adk_agent_host: str = "127.0.0.1"
    adk_agent_port: int = 8001
    adk_agent_url: str = "http://127.0.0.1:8001"
    a2a_timeout_seconds: int = 60

    # ── MCP ──────────────────────────────────────────────────────────
    mcp_server_host: str = "127.0.0.1"
    mcp_server_port: int = 8002

    # ── Data Directories ─────────────────────────────────────────────
    data_dir: str = "data"
    uploads_dir: str = "data/uploads"
    vector_store_dir: str = "data/vector_store"
    sessions_dir: str = "data/sessions"
    eval_results_dir: str = "evaluation_data/results"

    # ── Security ─────────────────────────────────────────────────────
    max_query_length: int = 2000
    enable_injection_detection: bool = True

    # ── Observability ────────────────────────────────────────────────
    otel_enabled: bool = False
    otel_endpoint: str = "http://localhost:4317"

    # ── Cost Estimation (Gemini 2.5 Flash, Oct 2026 estimate) ────────
    # Prices are ESTIMATES — label appropriately, do not claim exact billing.
    input_token_cost_per_million: float = 0.075
    output_token_cost_per_million: float = 0.30
    cost_model_label: str = "gemini-2.5-flash (estimate, Oct 2026)"

    # ── Paths (computed) ─────────────────────────────────────────────
    @property
    def uploads_path(self) -> Path:
        return Path(self.uploads_dir)

    @property
    def vector_store_path(self) -> Path:
        return Path(self.vector_store_dir)

    @property
    def blackboard_path(self) -> Path:
        return Path(self.blackboard_db_path)

    def ensure_dirs(self) -> None:
        """Create required data directories if they don't exist."""
        for d in [self.data_dir, self.uploads_dir, self.vector_store_dir,
                  self.sessions_dir, self.eval_results_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)

    def get_crewai_llm(self):
        """Return a CrewAI-compatible LLM object. Returns None if no key configured."""
        try:
            from crewai import LLM
            if self.google_api_key:
                return LLM(
                    model=self.crewai_llm_model,
                    api_key=self.google_api_key,
                    temperature=0.2,
                )
            elif self.groq_api_key:
                return LLM(
                    model="groq/llama-3.1-70b-versatile",
                    api_key=self.groq_api_key,
                    temperature=0.2,
                )
            elif self.openai_api_key:
                return LLM(
                    model="gpt-4o-mini",
                    api_key=self.openai_api_key,
                    temperature=0.2,
                )
        except Exception:
            pass
        return None

    def has_llm_configured(self) -> bool:
        """True if at least one LLM provider is configured."""
        return bool(self.google_api_key or self.groq_api_key or self.openai_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
