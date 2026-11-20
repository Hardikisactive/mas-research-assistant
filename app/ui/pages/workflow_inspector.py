"""Workflow Inspector / Blackboard page."""
import json
import streamlit as st
from app.state.blackboard import get_blackboard


def _show_df(df, **kwargs):
    """Render a DataFrame safely without triggering pyarrow/numpy conflicts."""
    import pandas as pd
    # Convert every column to str — pyarrow is only triggered for typed arrays
    safe = df.copy()
    for col in safe.columns:
        safe[col] = safe[col].astype(str).replace("nan", "—").replace("None", "—")
    try:
        st.dataframe(safe, **kwargs)
    except Exception:
        st.markdown(safe.to_html(index=False), unsafe_allow_html=True)


def render():
    st.header("🔍 Workflow Inspector & Blackboard")
    bb = get_blackboard()

    runs = bb.list_runs(limit=50)

    if not runs:
        st.info("No workflow runs recorded yet. Run a query from the Chat page first.")
        return

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Recent Runs")
        run_options = {
            f"{r['run_id'][:8]}… | {r['workflow_pattern']} | {r['current_status']}": r["run_id"]
            for r in runs
        }
        selected_label = st.selectbox("Select run", list(run_options.keys()))
        selected_run_id = run_options[selected_label]

    with col2:
        if selected_run_id:
            run = bb.get_run(selected_run_id)
            if run:
                status_color = {
                    "COMPLETED": "🟢", "RUNNING": "🟡",
                    "FAILED": "🔴", "PENDING": "⚪", "REJECTED": "🔴",
                }.get(run.get("current_status", ""), "⚪")

                st.subheader(f"{status_color} Run: `{selected_run_id[:16]}…`")
                c1, c2, c3 = st.columns(3)
                c1.metric("Status", run.get("current_status", "N/A"))
                c2.metric("Pattern", run.get("workflow_pattern", "N/A"))
                c3.metric("Persona", run.get("persona", "N/A"))

                st.markdown(f"**Query:** {run.get('original_query', '')[:200]}")

                tab_state, tab_events, tab_tools, tab_audit = st.tabs(
                    ["🗂 Full State", "📋 Agent Events", "🔧 Tool Calls", "📜 Audit Log"]
                )

                with tab_state:
                    # Show key fields cleanly
                    for field in ["current_status", "selected_agents", "agent_outputs",
                                  "critic_results", "errors", "retry_count"]:
                        val = run.get(field)
                        if val is not None and val not in ({}, [], ""):
                            with st.expander(f"**{field}**"):
                                st.json(val)

                    st.caption(f"Version: {run.get('version', 1)} | "
                               f"Created: {run.get('created_at', '')[:19]} | "
                               f"Updated: {run.get('updated_at', '')[:19]}")

                with tab_events:
                    events = bb.get_events(selected_run_id)
                    if events:
                        import pandas as pd
                        df = pd.DataFrame(events)[
                            ["agent_name", "event_type", "status",
                             "duration_ms", "summary", "timestamp"]
                        ]
                        _show_df(df, use_container_width=True)
                    else:
                        st.info("No events recorded.")

                with tab_tools:
                    tools = bb.get_tool_calls(selected_run_id)
                    if tools:
                        import pandas as pd
                        df = pd.DataFrame(tools)[
                            ["tool_name", "agent_name", "success",
                             "duration_ms", "input_summary", "timestamp"]
                        ]
                        df["success"] = df["success"].map({1: "✅", 0: "❌"})
                        _show_df(df, use_container_width=True)
                    else:
                        st.info("No tool calls recorded.")

                with tab_audit:
                    audit = bb.get_audit_log(selected_run_id, limit=50)
                    if audit:
                        import pandas as pd
                        df = pd.DataFrame(audit)[
                            ["action", "actor", "field_name",
                             "old_version", "new_version", "timestamp"]
                        ]
                        _show_df(df, use_container_width=True)
                    else:
                        st.info("No audit entries.")

                if run.get("final_output"):
                    st.divider()
                    st.subheader("Final Output")
                    with st.expander("View JSON"):
                        st.json(run["final_output"])

