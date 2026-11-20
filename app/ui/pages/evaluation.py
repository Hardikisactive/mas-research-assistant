"""Evaluation Results page."""
import json
import os
import streamlit as st
from pathlib import Path
from app.evaluation.charts import load_all_results, get_dashboard_metrics

RESULTS_DIR = Path("evaluation_data/results")


def _show_df(df, **kwargs):
    """Render DataFrame without triggering pyarrow/numpy version conflicts."""
    safe = df.copy()
    for col in safe.columns:
        safe[col] = safe[col].astype(str).replace("nan", "—").replace("None", "—")
    try:
        st.dataframe(safe, **kwargs)
    except Exception:
        st.markdown(safe.to_html(index=False), unsafe_allow_html=True)


def render():
    st.header("🧪 Evaluation Results")

    result_files = sorted(RESULTS_DIR.glob("eval_*.json"), reverse=True) if RESULTS_DIR.exists() else []

    if not result_files:
        st.warning(
            "No evaluation results found.\n\n"
            "Run the evaluation harness:\n"
            "```bash\n"
            "cd e:\\PRJ-4\\mas_project\n"
            "python -m app.evaluation.harness --patterns BASELINE HIERARCHICAL PARALLEL SEQUENTIAL\n"
            "```\n"
            "For a quick dry-run (no API calls):\n"
            "```bash\n"
            "python -m app.evaluation.harness --patterns HIERARCHICAL --dry-run\n"
            "```"
        )
        # Quick dry-run button
        if st.button("▶️ Run Quick Dry-Run (no API calls, ~50 records)"):
            with st.spinner("Running dry-run evaluation…"):
                import sys
                sys.path.insert(0, str(Path(".")))
                from app.evaluation.harness import run_evaluation
                recs = run_evaluation(
                    patterns=["HIERARCHICAL", "BASELINE"],
                    dry_run=True,
                )
            st.success(f"Generated {len(recs)} dry-run records.")
            st.rerun()
        return

    # File selector
    file_labels = [f.name for f in result_files]
    selected_file = st.selectbox("Select result file", file_labels)
    records = []
    try:
        with open(RESULTS_DIR / selected_file, encoding="utf-8") as f:
            records = json.load(f)
    except Exception as e:
        st.error(f"Failed to load: {e}")
        return

    st.success(f"Loaded {len(records)} records from `{selected_file}`")

    metrics = get_dashboard_metrics(records)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Runs", metrics["total"])
    c2.metric("Completed", metrics.get("completed", 0))
    c3.metric("Completion Rate", f"{metrics.get('completion_rate', 0):.1f}%")
    c4.metric("Avg Latency", f"{metrics.get('avg_latency_ms', 0) or 0:.0f}ms")

    st.caption(f"⚠️ {metrics.get('note', '')}")

    # Filters
    st.subheader("Filter & Explore")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        patterns = ["ALL"] + sorted(set(r.get("workflow_pattern", "") for r in records))
        pat_filter = st.selectbox("Pattern", patterns)
    with col_f2:
        personas = ["ALL"] + sorted(set(r.get("persona", "") for r in records))
        persona_filter = st.selectbox("Persona", personas)
    with col_f3:
        show_security = st.checkbox("Security tests only", value=False)

    filtered = records
    if pat_filter != "ALL":
        filtered = [r for r in filtered if r.get("workflow_pattern") == pat_filter]
    if persona_filter != "ALL":
        filtered = [r for r in filtered if r.get("persona") == persona_filter]
    if show_security:
        filtered = [r for r in filtered if r.get("is_security_test")]

    st.markdown(f"Showing **{len(filtered)}** records")

    # Table — pyarrow-safe rendering
    import pandas as pd
    if filtered:
        display_cols = [
            "test_case_id", "workflow_pattern", "persona",
            "task_completed", "correctness_score", "groundedness_score",
            "latency_ms", "total_cost_usd", "security_passed", "error_occurred"
        ]
        avail_cols = [c for c in display_cols if c in filtered[0]]
        df = pd.DataFrame(filtered)[avail_cols].copy()
        if "task_completed" in df.columns:
            df["task_completed"] = df["task_completed"].map({True: "✅", False: "❌"})
        if "error_occurred" in df.columns:
            df["error_occurred"] = df["error_occurred"].map({True: "🔴", False: "🟢"})
        if "security_passed" in df.columns:
            df["security_passed"] = df["security_passed"].map({True: "✅", False: "❌"})

        # Convert all columns to strings — bypasses pyarrow entirely
        for col in df.columns:
            df[col] = df[col].astype(str).replace("nan", "—")

        _show_df(df, use_container_width=True)

    # Download buttons
    col_dl1, col_dl2 = st.columns(2)
    with col_dl1:
        st.download_button(
            "⬇️ Download CSV",
            data=pd.DataFrame(filtered).to_csv(index=False).encode(),
            file_name=f"eval_results_{selected_file.replace('.json','.csv')}",
            mime="text/csv",
        )
    with col_dl2:
        st.download_button(
            "⬇️ Download JSON",
            data=json.dumps(filtered, indent=2, default=str),
            file_name=selected_file,
            mime="application/json",
        )

    # Run new eval button
    st.divider()
    st.subheader("Run New Evaluation")
    eval_patterns = st.multiselect(
        "Patterns to run",
        ["BASELINE", "HIERARCHICAL", "PARALLEL", "SEQUENTIAL"],
        default=["HIERARCHICAL"],
    )
    eval_limit = st.number_input("Max cases per pattern", min_value=1, max_value=50, value=5)
    dry_run = st.checkbox("Dry run (no API calls)", value=not bool(__import__("app.config.settings", fromlist=["get_settings"]).get_settings().has_llm_configured()))

    if st.button("▶️ Run Evaluation", disabled=not eval_patterns):
        with st.spinner(f"Running {eval_patterns} × {eval_limit} cases…"):
            from app.evaluation.harness import run_evaluation
            new_recs = run_evaluation(
                patterns=eval_patterns,
                limit=int(eval_limit),
                dry_run=dry_run,
            )
        st.success(f"✅ Generated {len(new_recs)} records.")
        st.rerun()

