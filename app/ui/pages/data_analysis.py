"""Data Analysis page."""
import json
import streamlit as st
from pathlib import Path
from app.config.settings import get_settings
from app.security.guardrails import validate_file_upload, GuardrailViolation


def _show_df(df, **kwargs):
    """Render DataFrame without pyarrow/numpy version conflicts."""
    import pandas as pd
    safe = df.copy()
    # Drop styled objects — re-apply as plain df
    if hasattr(safe, "data"):
        safe = safe.data
    for col in safe.columns:
        safe[col] = safe[col].astype(str).replace("nan", "—").replace("None", "—")
    try:
        st.dataframe(safe, **kwargs)
    except Exception:
        st.markdown(safe.to_html(index=False), unsafe_allow_html=True)


def render():
    st.header("📊 Data Analysis")
    settings = get_settings()
    uploads_dir = Path(settings.uploads_dir)

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Upload CSV Dataset")
        uploaded = st.file_uploader("Upload CSV file", type=["csv"])
        if uploaded:
            try:
                safe_name, _ = validate_file_upload(
                    uploaded.name, len(uploaded.getvalue()),
                    max_size_mb=settings.max_file_size_mb,
                )
                save_path = uploads_dir / safe_name
                with open(save_path, "wb") as f:
                    f.write(uploaded.getvalue())
                st.success(f"✅ Saved: {safe_name}")
            except GuardrailViolation as e:
                st.error(f"❌ {e}")

    with col2:
        st.subheader("Available Datasets")
        csv_files = list(uploads_dir.glob("*.csv")) if uploads_dir.exists() else []
        if csv_files:
            for f in csv_files:
                st.markdown(f"📊 `{f.name}` ({f.stat().st_size // 1024} KB)")
        else:
            st.info("No CSV files uploaded yet.")

    st.divider()

    # Quick analysis via agent
    st.subheader("Run Analysis")
    avail_csvs = [f.name for f in uploads_dir.glob("*.csv")] if uploads_dir.exists() else []

    if not avail_csvs:
        st.warning("Upload a CSV file first.")
        return

    filename = st.selectbox("Select dataset", avail_csvs)
    analysis_type = st.selectbox(
        "Analysis type", ["summary", "correlation", "missing"],
        help="summary: descriptive stats | correlation: correlation matrix | missing: null analysis"
    )
    query = st.text_input(
        "Natural language question (optional)",
        placeholder="e.g. What is the average brightness in this dataset?"
    )

    if st.button("🔬 Analyse", type="primary"):
        with st.spinner("Running data analysis…"):
            # Direct tool call for immediate feedback
            from app.agents.data_analysis.agent import DataAnalysisTool
            tool = DataAnalysisTool()
            raw = tool._run(filename=filename, analysis_type=analysis_type)
            try:
                result = json.loads(raw)
            except Exception:
                result = {"error": raw}

        if result.get("success"):
            tab_sum, tab_dtypes, tab_null, tab_corr, tab_sample = st.tabs(
                ["Summary", "Schema", "Missing Values", "Correlation", "Sample Rows"]
            )
            with tab_sum:
                if "numeric_summary" in result:
                    import pandas as pd
                    df_desc = pd.DataFrame(result["numeric_summary"])
                    _show_df(df_desc, use_container_width=True)
                    st.caption(f"Shape: {result.get('shape', 'N/A')}")
                if "categorical_summary" in result:
                    st.subheader("Categorical Columns (Top 5 values)")
                    for col, counts in result["categorical_summary"].items():
                        st.markdown(f"**{col}**: {counts}")

            with tab_dtypes:
                st.json(result.get("dtypes", {}))

            with tab_null:
                null_data = result.get("null_counts", {})
                if null_data:
                    import pandas as pd
                    null_df = pd.DataFrame(
                        {"column": list(null_data.keys()),
                         "null_count": list(null_data.values()),
                         "null_pct": [result.get("null_pct", {}).get(k, 0)
                                      for k in null_data.keys()]}
                    )
                    _show_df(null_df, use_container_width=True)
            with tab_corr:
                if "correlation_matrix" in result:
                    import pandas as pd
                    corr_df = pd.DataFrame(result["correlation_matrix"])
                    _show_df(corr_df, use_container_width=True)
                else:
                    st.info("Run with analysis_type=correlation to see this.")

            with tab_sample:
                if "sample_rows" in result:
                    import pandas as pd
                    _show_df(pd.DataFrame(result["sample_rows"]), use_container_width=True)

            # If natural language question given, use full workflow
            if query.strip():
                st.divider()
                st.subheader("Natural Language Answer")
                with st.spinner("Running data analysis agent…"):
                    from app.workflows.engine import run_workflow
                    resp = run_workflow(
                        query=f"{query} (Dataset: {filename})",
                        pattern="HIERARCHICAL",
                        persona="DATA_ANALYST",
                    )
                st.markdown(resp.answer)
                if resp.is_mock:
                    st.warning("⚠️ Mock mode — no real LLM calls")
        else:
            st.error(f"Analysis failed: {result.get('error', 'Unknown error')}")

