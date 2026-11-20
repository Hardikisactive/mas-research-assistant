"""
MCP Tool Server using FastMCP.
Exposes: web_search, document_retrieval, calculator, data_profiler
Run standalone: python -m app.tools.mcp.server
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from mcp.server.fastmcp import FastMCP
import json
import logging
import math
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)
mcp = FastMCP("MAS Research Tools")


# ---------------------------------------------------------------------------
# Tool 1: web_search
# ---------------------------------------------------------------------------

@mcp.tool()
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for current information on a topic. Returns title, URL, snippet, and source metadata."""
    # Security: strip whitespace, reject empty queries, truncate to 500 chars
    query = query.strip()
    if not query:
        return json.dumps({"error": "Empty query provided", "results": [], "tool_available": False})

    if len(query) > 500:
        query = query[:500]

    if not (1 <= max_results <= 10):
        max_results = max(1, min(10, max_results))

    logger.info(f"web_search called: query_len={len(query)}, max_results={max_results}")

    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    try:
        raw = DDGS().text(query, max_results=max_results)
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
                "source": "duckduckgo",
            }
            for r in (raw or [])
        ]
        return json.dumps({"results": results, "query": query, "result_count": len(results)})
    except Exception as e:
        logger.error(f"web_search error: {e}")
        return json.dumps({"error": str(e), "results": [], "tool_available": False})


# ---------------------------------------------------------------------------
# Tool 2: document_retrieval
# ---------------------------------------------------------------------------

@mcp.tool()
def document_retrieval(query: str, top_k: int = 5, document_filter: Optional[str] = None) -> str:
    """Retrieve relevant chunks from indexed documents using semantic search."""
    top_k = max(1, min(20, top_k))
    index_path = Path("data/vector_store/index.faiss")

    if not index_path.exists():
        return json.dumps({"error": "No documents indexed", "chunks": [], "tool_available": False})

    try:
        import faiss  # type: ignore
        import numpy as np
        from sentence_transformers import SentenceTransformer  # type: ignore

        model = SentenceTransformer("all-MiniLM-L6-v2")
        query_vec = model.encode([query], convert_to_numpy=True).astype("float32")
        faiss.normalize_L2(query_vec)

        index = faiss.read_index(str(index_path))
        distances, indices = index.search(query_vec, top_k)

        # Load metadata if available
        meta_path = Path("data/vector_store/metadata.json")
        metadata = {}
        if meta_path.exists():
            with open(meta_path) as f:
                metadata = json.load(f)

        chunks = []
        for rank, (dist, idx) in enumerate(zip(distances[0], indices[0])):
            if idx == -1:
                continue
            meta = metadata.get(str(idx), {})
            if document_filter and meta.get("document_id") != document_filter:
                continue
            chunks.append({
                "chunk_id": int(idx),
                "text": meta.get("text", ""),
                "score": float(dist),
                "document_id": meta.get("document_id", ""),
                "filename": meta.get("filename", ""),
            })

        return json.dumps({"chunks": chunks, "query": query, "found": len(chunks)})
    except ImportError as e:
        return json.dumps({"error": f"Required library not available: {e}", "chunks": [], "tool_available": False})
    except Exception as e:
        logger.error(f"document_retrieval error: {e}")
        return json.dumps({"error": str(e), "chunks": [], "tool_available": False})


# ---------------------------------------------------------------------------
# Tool 3: calculator
# ---------------------------------------------------------------------------

@mcp.tool()
def calculator(expression: str) -> str:
    """Perform safe mathematical calculations using Python eval with a restricted namespace."""
    if len(expression) > 200:
        return json.dumps({"expression": expression[:200], "error": "Expression exceeds 200 character limit"})

    safe_ns = {
        "__builtins__": {},
        "math": math,
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "len": len,
    }

    try:
        result = eval(expression, safe_ns)  # noqa: S307 — restricted namespace
        return json.dumps({"expression": expression, "result": result})
    except Exception as e:
        return json.dumps({"expression": expression, "error": str(e)})


# ---------------------------------------------------------------------------
# Tool 4: data_profiler
# ---------------------------------------------------------------------------

@mcp.tool()
def data_profiler(filename: str, max_rows: int = 1000) -> str:
    """Profile a CSV file and return summary statistics. File must be in the allowed uploads directory."""
    # Security: reject path traversal and absolute paths
    if ".." in filename or os.path.isabs(filename):
        return json.dumps({"error": "Invalid filename: path traversal not allowed", "tool_available": False})

    # Strip any directory components — only the bare filename is accepted
    safe_name = Path(filename).name
    uploads_dir = Path("data/uploads")
    file_path = uploads_dir / safe_name

    if not file_path.exists():
        return json.dumps({"error": f"File not found: {safe_name}", "tool_available": False})

    try:
        import pandas as pd  # type: ignore

        df = pd.read_csv(file_path, nrows=max_rows)

        numeric_summary = df.describe().to_dict()
        # Convert numpy types for JSON serialisation
        def _serialisable(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return str(v)

        numeric_summary = {
            col: {k: _serialisable(v) for k, v in stats.items()}
            for col, stats in numeric_summary.items()
        }

        return json.dumps({
            "shape": list(df.shape),
            "columns": df.columns.tolist(),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "null_counts": df.isnull().sum().to_dict(),
            "numeric_summary": numeric_summary,
            "sample_rows": df.head(3).to_dict(orient="records"),
        })
    except Exception as e:
        logger.error(f"data_profiler error: {e}")
        return json.dumps({"error": str(e), "tool_available": False})


if __name__ == "__main__":
    mcp.run()

