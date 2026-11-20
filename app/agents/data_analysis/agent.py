"""
CrewAI Data Analysis Agent.
Analyzes CSV/tabular data using Pandas, NumPy, and Scikit-learn.
Operates on allowlisted operations only — never executes arbitrary user code.

Framework: CrewAI
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

from crewai import Agent, LLM
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from app.config.settings import get_settings
from app.security.validators import validate_csv_path

logger = logging.getLogger(__name__)


class DataProfileInput(BaseModel):
    filename: str = Field(description="CSV filename (in uploads directory)")
    analysis_type: str = Field(
        default="summary",
        description="Type: summary|correlation|distribution|missing",
    )
    columns: Optional[list[str]] = Field(
        default=None,
        description="Optional list of columns to focus on",
    )


class DataAnalysisTool(BaseTool):
    """
    Safe CSV analysis tool. Only reads files from the uploads directory.
    Performs allowlisted operations; does NOT execute user-supplied code.
    """
    name: str = "data_analysis"
    description: str = (
        "Analyze a CSV file. Provide filename and analysis type "
        "(summary, correlation, distribution, missing). "
        "Returns statistics, schema, and insights."
    )
    args_schema: type[BaseModel] = DataProfileInput

    def _run(
        self,
        filename: str,
        analysis_type: str = "summary",
        columns: Optional[list[str]] = None,
    ) -> str:
        settings = get_settings()
        uploads_dir = settings.uploads_dir

        # Security: validate path
        try:
            safe_path = validate_csv_path(filename, uploads_dir)
        except (ValueError, PermissionError) as e:
            return json.dumps({"error": str(e), "success": False})

        if not safe_path.exists():
            return json.dumps({
                "error": f"File '{filename}' not found in uploads directory.",
                "success": False,
            })

        try:
            import pandas as pd
            import numpy as np

            df = pd.read_csv(str(safe_path), nrows=10_000)  # Limit rows

            # Filter columns if specified
            if columns:
                valid_cols = [c for c in columns if c in df.columns]
                if valid_cols:
                    df = df[valid_cols]

            result = {
                "success": True,
                "filename": filename,
                "shape": list(df.shape),
                "columns": list(df.columns),
                "dtypes": {c: str(t) for c, t in df.dtypes.items()},
                "null_counts": df.isnull().sum().to_dict(),
                "null_pct": (df.isnull().sum() / len(df) * 100).round(2).to_dict(),
            }

            if analysis_type in ("summary", "all"):
                import numpy as np
                numeric_df = df.select_dtypes(include=[np.number])
                if not numeric_df.empty:
                    desc = numeric_df.describe().round(4)
                    result["numeric_summary"] = desc.to_dict()
                cat_df = df.select_dtypes(include=["object", "category"])
                if not cat_df.empty:
                    result["categorical_summary"] = {
                        c: df[c].value_counts().head(5).to_dict()
                        for c in cat_df.columns[:10]
                    }

            if analysis_type == "correlation":
                import numpy as np
                numeric_df = df.select_dtypes(include=[np.number])
                if len(numeric_df.columns) >= 2:
                    corr = numeric_df.corr().round(4)
                    result["correlation_matrix"] = corr.to_dict()

            if analysis_type == "missing":
                result["missing_analysis"] = {
                    c: {
                        "count": int(df[c].isnull().sum()),
                        "pct": float(df[c].isnull().sum() / len(df) * 100),
                    }
                    for c in df.columns
                }

            # Sample rows
            result["sample_rows"] = df.head(3).to_dict(orient="records")

            logger.info(
                f"DataAnalysis: {filename} shape={df.shape} type={analysis_type}"
            )
            return json.dumps(result, default=str)

        except Exception as exc:
            logger.error(f"Data analysis failed for {filename}: {exc}")
            return json.dumps({"error": str(exc)[:300], "success": False})


def build_data_analysis_agent(llm=None) -> Agent:
    """Create and return the CrewAI Data Analysis Agent."""
    settings = get_settings()
    if llm is None:
        llm = settings.get_crewai_llm()

    return Agent(
        role="Data Analysis Specialist",
        goal=(
            "Analyze CSV and tabular datasets to extract meaningful insights, statistics, "
            "and patterns. Report findings clearly with assumptions and limitations stated."
        ),
        backstory=(
            "You are an expert data scientist specializing in exploratory data analysis. "
            "You use pandas and numpy to inspect, clean, and analyze datasets. "
            "You report exactly what the data shows — you never fabricate statistics. "
            "When data is missing, corrupted, or insufficient for a conclusion, you say so. "
            "You document all data transformations and assumptions."
        ),
        tools=[DataAnalysisTool()],
        verbose=True,
        allow_delegation=False,
        llm=llm,
        max_iter=3,
        memory=False,
    )
