"""Settings & Health Status page."""
import sys
import streamlit as st
from app.config.settings import get_settings
from app.state.blackboard import get_blackboard
from app.protocols.a2a.client import A2AClient
from app.storage.vector_store import VectorStore


def render():
    st.header("⚙️ Settings & Health Status")
    settings = get_settings()

    # ── Health Checks ─────────────────────────────────────────────────
    st.subheader("Component Health")
    cols = st.columns(4)

    # LLM
    with cols[0]:
        if settings.has_llm_configured():
            st.success("✅ LLM\nConfigured")
        else:
            st.error("❌ LLM\nNo API key")

    # Blackboard
    with cols[1]:
        try:
            bb = get_blackboard()
            runs = bb.list_runs(limit=1)
            st.success("✅ Blackboard\nSQLite OK")
        except Exception as e:
            st.error(f"❌ Blackboard\n{e}")

    # Vector Store
    with cols[2]:
        try:
            vs = VectorStore(settings.vector_store_dir, settings.embedding_model)
            if vs.is_available:
                st.success(f"✅ Vector Store\n{vs.total_chunks} chunks")
            else:
                st.warning("⚠️ Vector Store\nFAISS unavailable")
        except Exception as e:
            st.error(f"❌ Vector Store\n{e}")

    # A2A / ADK Server
    with cols[3]:
        try:
            client = A2AClient()
            health = client.check_health()
            if health.get("reachable"):
                st.success("✅ ADK A2A\nServer online")
            else:
                st.warning("⚠️ ADK A2A\nServer offline\n(fallback active)")
        except Exception as e:
            st.warning(f"⚠️ ADK A2A\n{e}")

    st.divider()

    # ── Configuration ─────────────────────────────────────────────────
    st.subheader("Configuration")
    st.info(
        "API keys are loaded from `.env`. Never enter them here — "
        "configure them in your `.env` file.",
        icon="🔒",
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**LLM Settings**")
        st.code(f"CrewAI model: {settings.crewai_llm_model}\n"
                f"ADK model:    {settings.adk_model}\n"
                f"Provider:     {'Google Gemini' if settings.google_api_key else 'Not configured'}")

        st.markdown("**RAG Settings**")
        st.code(f"Embedding:   {settings.embedding_model}\n"
                f"Chunk size:  {settings.chunk_size} words\n"
                f"Overlap:     {settings.chunk_overlap} words\n"
                f"Top-K:       {settings.retrieval_top_k}")

    with col2:
        st.markdown("**A2A / MCP Endpoints**")
        st.code(f"ADK Agent:   {settings.adk_agent_url}\n"
                f"MCP Server:  {settings.mcp_server_host}:{settings.mcp_server_port}\n"
                f"App Port:    {settings.app_port}")

        st.markdown("**Security**")
        st.code(f"Max query:   {settings.max_query_length} chars\n"
                f"Max file:    {settings.max_file_size_mb} MB\n"
                f"Injection:   {'enabled' if settings.enable_injection_detection else 'disabled'}")

    st.divider()

    # ── Start A2A Server ──────────────────────────────────────────────
    st.subheader("Service Management")
    st.markdown(
        "Start the ADK RAG Agent A2A server (required for cross-framework communication):"
    )
    st.code(
        "# In a separate terminal:\n"
        "cd e:\\PRJ-4\\mas_project\n"
        "python -m app.protocols.a2a.server",
        language="bash",
    )
    st.markdown("Start the MCP Tool Server:")
    st.code(
        "cd e:\\PRJ-4\\mas_project\n"
        "python -m app.tools.mcp.server",
        language="bash",
    )

    st.divider()

    # ── System Info ───────────────────────────────────────────────────
    st.subheader("System Information")
    st.code(
        f"Python:       {sys.version.split()[0]}\n"
        f"Streamlit:    {st.__version__}\n"
        f"DB path:      {settings.blackboard_db_path}\n"
        f"Uploads dir:  {settings.uploads_dir}\n"
        f"Vector store: {settings.vector_store_dir}\n"
        f"Eval results: {settings.eval_results_dir}"
    )

    # Cost estimate disclaimer
    st.divider()
    st.caption(
        "💡 Cost estimates are based on assumed pricing (Gemini 1.5 Flash, Oct 2026). "
        "Actual billing may differ. See `app/config/pricing.py` for the pricing table."
    )

