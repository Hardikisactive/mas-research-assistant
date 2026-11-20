"""
Multi-Agent Research Assistant — Streamlit Application
Main entry point. Run with: streamlit run app/ui/app.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[2]))

import streamlit as st

from app.observability.logger import setup_logging
from app.config.settings import get_settings

setup_logging("INFO")
settings = get_settings()
settings.ensure_dirs()

st.set_page_config(
    page_title="MAS Research Assistant",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🤖 MAS Research Assistant")
    st.caption("Multi-Agent Research & Knowledge System")
    st.divider()

    page = st.selectbox(
        "Navigate",
        [
            "💬 Chat / Research",
            "📄 Document Upload & RAG",
            "📊 Data Analysis",
            "🔍 Workflow Inspector",
            "📈 Observability Dashboard",
            "🧪 Evaluation Results",
            "⚙️ Settings & Health",
        ],
    )
    st.divider()

    # API key status
    if settings.google_api_key:
        st.success("✅ Google API Key configured")
    else:
        st.warning("⚠️ GOOGLE_API_KEY not set\nRunning in mock mode")

    st.caption(f"v1.0 | Python {sys.version.split()[0]}")

# ── Page routing ─────────────────────────────────────────────────────────────
if page == "💬 Chat / Research":
    from app.ui.pages import chat
    chat.render()
elif page == "📄 Document Upload & RAG":
    from app.ui.pages import documents
    documents.render()
elif page == "📊 Data Analysis":
    from app.ui.pages import data_analysis
    data_analysis.render()
elif page == "🔍 Workflow Inspector":
    from app.ui.pages import workflow_inspector
    workflow_inspector.render()
elif page == "📈 Observability Dashboard":
    from app.ui.pages import dashboard
    dashboard.render()
elif page == "🧪 Evaluation Results":
    from app.ui.pages import evaluation
    evaluation.render()
elif page == "⚙️ Settings & Health":
    from app.ui.pages import settings as settings_page
    settings_page.render()

