"""Observability Dashboard page."""
import streamlit as st
from app.state.blackboard import get_blackboard
from app.observability.metrics import get_metrics
from app.evaluation.charts import load_all_results, get_dashboard_metrics


def _show_df(df, **kwargs):
    """Render a DataFrame safely without triggering pyarrow/numpy conflicts."""
    safe = df.copy()
    for col in safe.columns:
        safe[col] = safe[col].astype(str).replace("nan", "—").replace("None", "—")
    try:
        st.dataframe(safe, **kwargs)
    except Exception:
        st.markdown(safe.to_html(index=False), unsafe_allow_html=True)


def render():
    st.header("📈 Observability Dashboard")

    bb = get_blackboard()
    metrics = get_metrics()
    runs = bb.list_runs(limit=200)

    # ── Summary Metrics ────────────────────────────────────────────────
    st.subheader("System Summary")
    c1, c2, c3, c4 = st.columns(4)
    total = len(runs)
    completed = sum(1 for r in runs if r.get("current_status") == "COMPLETED")
    failed = sum(1 for r in runs if r.get("current_status") == "FAILED")

    c1.metric("Total Runs", total)
    c2.metric("Completed", completed)
    c3.metric("Failed", failed)
    c4.metric("Success Rate", f"{100*completed/total:.1f}%" if total else "N/A")

    st.divider()

    # ── Per-run metrics from in-process collector ─────────────────────
    live_runs = metrics.list_runs()
    if live_runs:
        st.subheader("Live Session Metrics")
        import pandas as pd
        rows = []
        for r in live_runs:
            rows.append({
                "run_id": r["run_id"][:12],
                "pattern": r.get("pattern", ""),
                "total_ms": round(r.get("total_ms", 0), 1),
                "input_tokens": r.get("input_tokens", 0),
                "output_tokens": r.get("output_tokens", 0),
                "est_cost_usd": round(r.get("estimated_cost_usd", 0), 6),
                "a2a_calls": r.get("a2a_calls", 0),
                "a2a_errors": r.get("a2a_errors", 0),
            })
        if rows:
            _show_df(pd.DataFrame(rows), use_container_width=True)

    st.divider()

    # ── Blackboard run table ───────────────────────────────────────────
    st.subheader("Blackboard Run History")
    if runs:
        import pandas as pd
        df = pd.DataFrame(runs)[
            ["run_id", "workflow_pattern", "current_status",
             "persona", "original_query", "created_at"]
        ]
        df["run_id"] = df["run_id"].str[:12] + "…"
        df["original_query"] = df["original_query"].str[:60] + "…"
        _show_df(df, use_container_width=True)
    else:
        st.info("No runs recorded yet.")

    st.divider()

    # ── Evaluation-derived charts ──────────────────────────────────────
    st.subheader("Evaluation Metrics (from evaluation harness)")
    eval_records = load_all_results()

    if not eval_records:
        st.info(
            "No evaluation results yet. Run:\n"
            "```\npython -m app.evaluation.harness --patterns HIERARCHICAL BASELINE\n```"
        )
        return

    metrics_dict = get_dashboard_metrics(eval_records)
    st.caption(f"Note: {metrics_dict.get('note', '')}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Eval Runs", metrics_dict["total"])
    c2.metric("Completion Rate", f"{metrics_dict.get('completion_rate', 0):.1f}%")
    c3.metric("Avg Latency", f"{metrics_dict.get('avg_latency_ms', 0):.0f}ms")
    c4.metric("Total Cost (est.)", f"${metrics_dict.get('total_cost_usd', 0):.4f}")

    c1, c2, c3 = st.columns(3)
    if metrics_dict.get("avg_correctness") is not None:
        c1.metric("Avg Correctness (heuristic)", f"{metrics_dict['avg_correctness']:.2f}")
    if metrics_dict.get("avg_groundedness") is not None:
        c2.metric("Avg Groundedness (heuristic)", f"{metrics_dict['avg_groundedness']:.2f}")
    if metrics_dict.get("security_pass_rate") is not None:
        c3.metric("Security Pass Rate", f"{metrics_dict['security_pass_rate']:.1f}%")

    # Charts
    from app.evaluation.charts import (
        generate_latency_boxplot, generate_agent_heatmap,
        generate_completion_bar_chart
    )
    col_a, col_b = st.columns(2)
    with col_a:
        fig = generate_latency_boxplot(eval_records)
        if fig:
            st.pyplot(fig)
        else:
            st.info("Latency boxplot: no data")

    with col_b:
        fig = generate_completion_bar_chart(eval_records)
        if fig:
            st.pyplot(fig)
        else:
            st.info("Completion chart: no data")

    fig = generate_agent_heatmap(eval_records)
    if fig:
        st.pyplot(fig)

    # Per-pattern table
    st.subheader("Per-Pattern Breakdown")
    import pandas as pd
    patterns = set(r.get("workflow_pattern", "") for r in eval_records)
    rows = []
    for pat in sorted(patterns):
        pat_recs = [r for r in eval_records if r.get("workflow_pattern") == pat]
        completed_n = sum(1 for r in pat_recs if r.get("task_completed"))
        lats = [r["latency_ms"] for r in pat_recs if r.get("latency_ms", 0) > 0]
        costs = [r["total_cost_usd"] for r in pat_recs if r.get("total_cost_usd", 0) > 0]
        rows.append({
            "Pattern": pat,
            "Runs": len(pat_recs),
            "Completed": completed_n,
            "Completion %": f"{100*completed_n/len(pat_recs):.1f}%" if pat_recs else "N/A",
            "Avg Latency (ms)": f"{sum(lats)/len(lats):.0f}" if lats else "N/A",
            "Total Cost (est. USD)": f"{sum(costs):.6f}" if costs else "0",
        })
    if rows:
        _show_df(pd.DataFrame(rows), use_container_width=True)
        st.caption("⚠️ Cost figures are estimates based on assumed pricing. See docs/evaluation_methodology.md")

