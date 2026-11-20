"""
startup.py — Auto-start background servers for Streamlit Cloud deployment.

On Streamlit Community Cloud only ONE process runs. This module starts
the A2A server (port 8002) and MCP server (port 8001) as daemon threads
so they're available to the agents inside the same process.

Called once from app/ui/app.py via:
    from app.startup import ensure_servers_running
    ensure_servers_running()
"""
from __future__ import annotations

import logging
import threading
import time
import socket

logger = logging.getLogger(__name__)

_servers_started = False
_lock = threading.Lock()


def _port_is_listening(port: int, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    """Return True if something is already listening on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _start_a2a_server() -> None:
    """Run the A2A FastAPI server in a daemon thread."""
    try:
        import uvicorn
        from app.protocols.a2a.server import app as a2a_app
        from app.config.settings import get_settings
        settings = get_settings()
        port = settings.a2a_server_port or 8002
        logger.info(f"[startup] Starting A2A server on port {port}")
        uvicorn.run(a2a_app, host="0.0.0.0", port=port, log_level="warning")
    except Exception as e:
        logger.error(f"[startup] A2A server failed to start: {e}")


def _start_mcp_server() -> None:
    """Run the MCP FastAPI wrapper in a daemon thread."""
    try:
        # MCP server uses SSE transport — wrap it with uvicorn on port 8001
        import uvicorn
        from app.tools.mcp.server import mcp
        from app.config.settings import get_settings
        settings = get_settings()
        port = settings.mcp_server_port or 8001
        logger.info(f"[startup] Starting MCP server on port {port}")
        # FastMCP exposes a Starlette/ASGI app via .sse_app()
        mcp_app = mcp.sse_app()
        uvicorn.run(mcp_app, host="0.0.0.0", port=port, log_level="warning")
    except Exception as e:
        logger.error(f"[startup] MCP server failed to start: {e}")


def ensure_servers_running() -> None:
    """
    Idempotent — safe to call on every Streamlit re-run.
    Starts A2A and MCP servers as daemon threads if not already running.
    """
    global _servers_started
    with _lock:
        if _servers_started:
            return

        from app.config.settings import get_settings
        settings = get_settings()
        a2a_port = settings.a2a_server_port or 8002
        mcp_port  = settings.mcp_server_port  or 8001

        # A2A server
        if _port_is_listening(a2a_port):
            logger.info(f"[startup] A2A server already running on port {a2a_port}")
        else:
            t = threading.Thread(target=_start_a2a_server, daemon=True, name="a2a-server")
            t.start()
            logger.info(f"[startup] A2A server thread started (port {a2a_port})")

        # MCP server
        if _port_is_listening(mcp_port):
            logger.info(f"[startup] MCP server already running on port {mcp_port}")
        else:
            t2 = threading.Thread(target=_start_mcp_server, daemon=True, name="mcp-server")
            t2.start()
            logger.info(f"[startup] MCP server thread started (port {mcp_port})")

        # Brief wait so servers are ready before first agent call
        time.sleep(2)
        _servers_started = True
        logger.info("[startup] Background servers initialised.")
