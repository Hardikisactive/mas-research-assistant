"""
Evaluation Charts — boxplots, heatmaps, bar charts from evaluation results.
Generates PNG files and returns chart data dicts for the Streamlit dashboard.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

RESULTS_DIR = Path("evaluation_data/results")


def load_latest_results(results_dir: Path = RESULTS_DIR) -> list[dict]:
    """Load the most recent evaluation results JSON file."""
    files = sorted(results_dir.glob("eval_*.json"), reverse=True)
    if not files:
        return []
    with open(files[0], encoding="utf-8") as f:
        return json.load(f)


def load_all_results(results_dir: Path = RESULTS_DIR) -> list[dict]:
    """Load and concatenate all evaluation result files."""
    all_records = []
    for f in sorted(results_dir.glob("eval_*.json")):
        try:
            with open(f, encoding="utf-8") as fp:
                all_records.extend(json.load(fp))
        except Exception as exc:
            logger.warning(f"Failed to load {f}: {exc}")
    return all_records


def generate_latency_boxplot(records: list[dict], output_path: Optional[str] = None):
    """
    Boxplot of end-to-end latency by workflow pattern.
    Returns: matplotlib Figure or None if matplotlib unavailable.
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np

        patterns = ["BASELINE", "HIERARCHICAL", "PARALLEL", "SEQUENTIAL"]
        data = []
        labels = []
        for pat in patterns:
            vals = [r["latency_ms"] for r in records
                    if str(r.get("workflow_pattern", "")) == pat and r.get("latency_ms", 0) > 0]
            if vals:
                data.append(vals)
                labels.append(pat)

        if not data:
            logger.warning("No latency data for boxplot")
            return None

        fig, ax = plt.subplots(figsize=(10, 6))
        bp = ax.boxplot(data, labels=labels, patch_artist=True)
        colors = ["#4CAF50", "#2196F3", "#FF9800", "#9C27B0"]
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)

        ax.set_title("End-to-End Latency by Workflow Pattern", fontsize=14, fontweight="bold")
        ax.set_xlabel("Workflow Pattern")
        ax.set_ylabel("Latency (ms)")
        ax.grid(axis="y", alpha=0.3)
        plt.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=150, bbox_inches="tight")
            logger.info(f"Saved latency boxplot: {output_path}")
        return fig
    except Exception as exc:
        logger.error(f"Boxplot error: {exc}")
        return None


def generate_agent_heatmap(records: list[dict], output_path: Optional[str] = None):
    """
    Agent-level heatmap: agents × metrics (success rate, avg latency, error rate).
    Returns: matplotlib Figure or None.
    """
    try:
        import matplotlib.pyplot as plt
        import numpy as np

        # Collect per-agent metrics from agent_events via run data
        # Use agents_invoked field from records
        agent_counts: dict[str, dict] = {}
        for r in records:
            for agent in r.get("agents_invoked", []):
                if agent not in agent_counts:
                    agent_counts[agent] = {"success": 0, "total": 0, "latency": []}
                agent_counts[agent]["total"] += 1
                if r.get("task_completed"):
                    agent_counts[agent]["success"] += 1

        if not agent_counts:
            return None

        agents = list(agent_counts.keys())
        metrics = ["Success Rate", "Invocation Count"]
        matrix = np.zeros((len(agents), len(metrics)))

        for i, agent in enumerate(agents):
            d = agent_counts[agent]
            matrix[i, 0] = d["success"] / max(d["total"], 1)
            matrix[i, 1] = d["total"] / max(len(records), 1)  # normalise

        fig, ax = plt.subplots(figsize=(8, max(4, len(agents) * 0.6 + 2)))
        im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto", vmin=0, vmax=1)
        ax.set_xticks(range(len(metrics)))
        ax.set_xticklabels(metrics)
        ax.set_yticks(range(len(agents)))
        ax.set_yticklabels(agents)

        for i in range(len(agents)):
            for j in range(len(metrics)):
                ax.text(j, i, f"{matrix[i,j]:.2f}", ha="center", va="center",
                        fontsize=9, color="black")

        plt.colorbar(im, ax=ax, label="Score (normalised)")
        ax.set_title("Agent Performance Heatmap", fontsize=13, fontweight="bold")
        plt.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=150, bbox_inches="tight")
            logger.info(f"Saved heatmap: {output_path}")
        return fig
    except Exception as exc:
        logger.error(f"Heatmap error: {exc}")
        return None


def generate_completion_bar_chart(records: list[dict], output_path: Optional[str] = None):
    """Bar chart of task completion rate by pattern."""
    try:
        import matplotlib.pyplot as plt
        patterns = ["BASELINE", "HIERARCHICAL", "PARALLEL", "SEQUENTIAL"]
        completion_rates = []
        labels = []
        for pat in patterns:
            pat_recs = [r for r in records if str(r.get("workflow_pattern")) == pat]
            if pat_recs:
                rate = sum(1 for r in pat_recs if r.get("task_completed")) / len(pat_recs)
                completion_rates.append(rate * 100)
                labels.append(pat)

        if not labels:
            return None

        fig, ax = plt.subplots(figsize=(8, 5))
        bars = ax.bar(labels, completion_rates,
                      color=["#4CAF50", "#2196F3", "#FF9800", "#9C27B0"])
        for bar, val in zip(bars, completion_rates):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                    f"{val:.1f}%", ha="center", fontsize=10, fontweight="bold")

        ax.set_title("Task Completion Rate by Workflow Pattern", fontsize=13, fontweight="bold")
        ax.set_ylabel("Completion Rate (%)")
        ax.set_ylim(0, 115)
        ax.grid(axis="y", alpha=0.3)
        plt.tight_layout()

        if output_path:
            fig.savefig(output_path, dpi=150, bbox_inches="tight")
        return fig
    except Exception as exc:
        logger.error(f"Bar chart error: {exc}")
        return None


def generate_all_charts(
    records: Optional[list[dict]] = None,
    output_dir: str = "evaluation_data/results/charts",
) -> dict[str, str]:
    """
    Generate all evaluation charts and save to output_dir.
    Returns dict of {chart_name: filepath}.
    """
    if records is None:
        records = load_all_results()

    if not records:
        logger.warning("No evaluation records found — charts not generated")
        return {}

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}

    fig = generate_latency_boxplot(records, str(out / "latency_boxplot.png"))
    if fig:
        paths["latency_boxplot"] = str(out / "latency_boxplot.png")

    fig = generate_agent_heatmap(records, str(out / "agent_heatmap.png"))
    if fig:
        paths["agent_heatmap"] = str(out / "agent_heatmap.png")

    fig = generate_completion_bar_chart(records, str(out / "completion_bar.png"))
    if fig:
        paths["completion_bar"] = str(out / "completion_bar.png")

    try:
        import matplotlib.pyplot as plt
        plt.close("all")
    except Exception:
        pass

    logger.info(f"Generated {len(paths)} charts in {out}")
    return paths


def get_dashboard_metrics(records: list[dict]) -> dict:
    """Compute summary metrics dict for the Streamlit dashboard."""
    if not records:
        return {"total": 0, "note": "No evaluation records found"}

    total = len(records)
    completed = sum(1 for r in records if r.get("task_completed"))
    errors = sum(1 for r in records if r.get("error_occurred"))
    latencies = [r["latency_ms"] for r in records if r.get("latency_ms", 0) > 0]
    costs = [r["total_cost_usd"] for r in records if r.get("total_cost_usd", 0) > 0]
    sec_records = [r for r in records if r.get("is_security_test")]
    sec_passed = sum(1 for r in sec_records if r.get("security_passed"))
    a2a_records = [r for r in records if r.get("a2a_success") is not None]
    a2a_success = sum(1 for r in a2a_records if r.get("a2a_success"))
    correctness = [r["correctness_score"] for r in records
                   if r.get("correctness_score") is not None]
    groundedness = [r["groundedness_score"] for r in records
                    if r.get("groundedness_score") is not None]

    import statistics
    return {
        "total": total,
        "completed": completed,
        "completion_rate": round(completed / total * 100, 1) if total else 0,
        "errors": errors,
        "avg_latency_ms": round(statistics.mean(latencies), 1) if latencies else None,
        "median_latency_ms": round(statistics.median(latencies), 1) if latencies else None,
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * len(latencies))], 1) if len(latencies) > 1 else None,
        "total_cost_usd": round(sum(costs), 6) if costs else 0,
        "avg_cost_usd": round(statistics.mean(costs), 8) if costs else 0,
        "security_pass_rate": round(sec_passed / len(sec_records) * 100, 1) if sec_records else None,
        "a2a_success_rate": round(a2a_success / len(a2a_records) * 100, 1) if a2a_records else None,
        "avg_correctness": round(statistics.mean(correctness), 3) if correctness else None,
        "avg_groundedness": round(statistics.mean(groundedness), 3) if groundedness else None,
        "is_estimate": True,
        "note": "Correctness/groundedness are heuristic scores, not ground-truth validated.",
    }

