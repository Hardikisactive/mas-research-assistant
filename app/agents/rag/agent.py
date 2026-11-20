"""
RAG Agent — retrieves relevant chunks from the FAISS vector store.
"""
from __future__ import annotations

import logging
from app.agents.base import BaseAgent

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a RAG (Retrieval-Augmented Generation) Agent.
Given retrieved document chunks, extract the most relevant information for the query.
Attribute information to specific documents where possible.
Output a concise, factual summary of what the documents say about the query."""


class RAGAgent(BaseAgent):
    """Retrieves and synthesises information from indexed documents."""
    name = "rag"
    role = "rag"

    def _execute(self, state: dict) -> dict:
        query = state.get("query", "")
        if not query:
            return {**state, "doc_results": [], "current_agent": "rag"}

        # Search vector store
        doc_results = []
        try:
            from app.storage.vector_store import get_vector_store
            vs = get_vector_store()
            doc_results = vs.search(query, top_k=5)
            logger.info(f"[rag] Retrieved {len(doc_results)} doc chunks")
        except Exception as e:
            logger.error(f"[rag] Vector search failed: {e}")

        # Sanitize retrieved text
        for r in doc_results:
            if "text" in r:
                r["text"] = self.safe_content(r["text"], source=f"doc:{r.get('filename','')}")

        # Summarize with LLM
        if doc_results:
            chunks_text = "\n\n".join(
                f"[{r.get('filename','Unknown')} | score={r.get('score',0):.2f}]\n{r.get('text','')}"
                for r in doc_results
            )
            prompt = (
                f"Query: {query}\n\n"
                f"Retrieved Document Chunks:\n{chunks_text}\n\n"
                "Based on these document chunks, what is the most relevant information for the query?"
            )
            doc_summary = self.llm_invoke(prompt, system=SYSTEM_PROMPT)
        else:
            doc_summary = "No relevant documents found in the index."

        return {
            **state,
            "doc_results": doc_results,
            "doc_summary": doc_summary,
            "current_agent": "rag",
        }
