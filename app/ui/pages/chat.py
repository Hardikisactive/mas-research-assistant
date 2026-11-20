"""Chat / Research page."""
import json, time
import streamlit as st
from app.workflows.engine import run_workflow
from app.config.settings import get_settings


def render():
    st.header("💬 Chat / Research Assistant")
    settings = get_settings()

    if not settings.has_llm_configured():
        st.info(
            "ℹ️ **Mock Mode** — No API key configured. Responses are stubs.\n"
            "Add `GOOGLE_API_KEY=your_key` to `.env` for real answers.",
            icon="ℹ️",
        )

    col1, col2 = st.columns([3, 1])
    with col1:
        query = st.text_area(
            "Research Question",
            placeholder="e.g. What are the latest advances in quantum computing?",
            height=100,
            max_chars=2000,
        )
    with col2:
        pattern = st.selectbox(
            "Workflow Pattern",
            ["HIERARCHICAL", "PARALLEL", "SEQUENTIAL", "BASELINE"],
            help=(
                "HIERARCHICAL: Supervisor delegates to specialists\n"
                "PARALLEL: Research + RAG run concurrently\n"
                "SEQUENTIAL: RAG → Verify → Synthesize\n"
                "BASELINE: Single LLM, no multi-agent"
            ),
        )
        persona = st.selectbox(
            "Persona",
            ["RESEARCHER", "STUDENT", "FACULTY_EVALUATOR", "DATA_ANALYST"],
        )

    if st.button("🚀 Run Research", type="primary", disabled=not query.strip()):
        with st.spinner(f"Running {pattern} workflow…"):
            t0 = time.perf_counter()
            try:
                response = run_workflow(query=query, pattern=pattern, persona=persona)
                elapsed = (time.perf_counter() - t0) * 1000
            except Exception as exc:
                st.error(f"Workflow error: {exc}")
                return

        # ── Results ──────────────────────────────────────────────────
        st.success(f"✅ Completed in {elapsed:.0f}ms | Run ID: `{response.run_id}`")

        if response.is_mock:
            st.warning("⚠️ Mock mode — no real LLM calls made")

        tab_answer, tab_sources, tab_evidence, tab_json = st.tabs(
            ["📝 Answer", "🔗 Sources", "📑 Evidence", "{}  JSON"]
        )

        with tab_answer:
            st.markdown(response.to_markdown())
            col_a, col_b, col_c = st.columns(3)
            col_a.metric("Verification", str(response.verification_status))
            col_b.metric("Agents", len(response.agents_used))
            col_c.metric("Latency", f"{elapsed:.0f}ms")

            if response.agents_used:
                st.caption(f"Agents used: {', '.join(response.agents_used)}")

        with tab_sources:
            if response.sources:
                for s in response.sources:
                    with st.expander(f"🔗 {s.title or s.url}"):
                        if s.url:
                            st.markdown(f"**URL:** {s.url}")
                        st.markdown(f"**Snippet:** {s.snippet[:400]}")
            else:
                st.info("No web sources retrieved for this query.")

        with tab_evidence:
            if response.document_evidence:
                for e in response.document_evidence:
                    with st.expander(
                        f"📄 {e.filename} — chunk {e.chunk_index} "
                        f"(score: {e.relevance_score:.2f})"
                    ):
                        st.markdown(f"> {e.text[:600]}")
            else:
                st.info("No document evidence retrieved. Upload documents first.")

        with tab_json:
            st.download_button(
                "⬇️ Download JSON",
                data=json.dumps(response.model_dump(mode="json"), indent=2),
                file_name=f"mas_response_{response.run_id[:8]}.json",
                mime="application/json",
            )
            st.json(response.model_dump(mode="json"))

    # History in session state
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

