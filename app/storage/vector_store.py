"""
RAG Pipeline: Document ingestion → chunking → embedding → FAISS indexing.
Handles PDF, TXT, DOCX with configurable chunk size/overlap.
All document IDs and chunk IDs are stable (hash-based).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Optional imports — handle gracefully if not installed
try:
    import faiss
    _FAISS_AVAILABLE = True
except ImportError:
    _FAISS_AVAILABLE = False
    logger.warning("faiss-cpu not installed — vector retrieval disabled")

try:
    from sentence_transformers import SentenceTransformer
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    logger.warning("sentence-transformers not installed — embeddings disabled")


class VectorStore:
    """
    FAISS-backed vector store with metadata in a JSON sidecar file.
    Embedding model: configurable sentence-transformers (default: all-MiniLM-L6-v2).
    """

    METADATA_FILE = "metadata.json"
    INDEX_FILE = "index.faiss"

    def __init__(
        self,
        store_dir: str = "data/vector_store",
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> None:
        self._store_dir = Path(store_dir)
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._embedding_model_name = embedding_model
        self._model: Optional[object] = None
        self._index: Optional[object] = None
        self._metadata: list[dict] = []
        self._load_existing()

    # ─── Embedding ───────────────────────────────────────────────────

    def _get_model(self):
        if self._model is None:
            if not _ST_AVAILABLE:
                raise RuntimeError("sentence-transformers not installed")
            logger.info(f"Loading embedding model: {self._embedding_model_name}")
            self._model = SentenceTransformer(self._embedding_model_name)
        return self._model

    def _embed(self, texts: list[str]) -> np.ndarray:
        model = self._get_model()
        vecs = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return np.array(vecs, dtype="float32")

    # ─── Persistence ─────────────────────────────────────────────────

    def _meta_path(self) -> Path:
        return self._store_dir / self.METADATA_FILE

    def _index_path(self) -> Path:
        return self._store_dir / self.INDEX_FILE

    def _load_existing(self) -> None:
        """Load index and metadata from disk if they exist."""
        if not _FAISS_AVAILABLE:
            return
        meta_path = self._meta_path()
        index_path = self._index_path()
        if meta_path.exists() and index_path.exists():
            try:
                with open(meta_path, encoding="utf-8") as f:
                    self._metadata = json.load(f)
                self._index = faiss.read_index(str(index_path))
                logger.info(
                    f"Loaded vector store: {self._index.ntotal} vectors, "
                    f"{len(self._metadata)} metadata entries"
                )
            except Exception as exc:
                logger.error(f"Failed to load vector store: {exc}")
                self._metadata = []
                self._index = None

    def _save(self) -> None:
        """Persist index and metadata to disk."""
        if not _FAISS_AVAILABLE or self._index is None:
            return
        faiss.write_index(self._index, str(self._index_path()))
        with open(self._meta_path(), "w", encoding="utf-8") as f:
            json.dump(self._metadata, f, indent=2)

    # ─── Indexing ────────────────────────────────────────────────────

    def add_chunks(
        self,
        chunks: list[dict],
        force_reindex: bool = False,
    ) -> int:
        """
        Add document chunks to the index.

        Args:
            chunks: List of dicts with keys: chunk_id, document_id, text,
                    filename, chunk_index, page_number (optional).
            force_reindex: If True, skip duplicate check.

        Returns:
            Number of new chunks added.
        """
        if not _FAISS_AVAILABLE or not _ST_AVAILABLE:
            logger.warning("Cannot index: FAISS or sentence-transformers unavailable")
            return 0

        # Deduplicate by chunk_id
        existing_ids = {m["chunk_id"] for m in self._metadata}
        new_chunks = [c for c in chunks
                      if force_reindex or c["chunk_id"] not in existing_ids]

        if not new_chunks:
            logger.info("All chunks already indexed — skipping")
            return 0

        texts = [c["text"] for c in new_chunks]
        vectors = self._embed(texts)

        if self._index is None:
            dim = vectors.shape[1]
            self._index = faiss.IndexFlatIP(dim)  # Inner product (cosine with normalized vecs)

        self._index.add(vectors)
        self._metadata.extend(new_chunks)
        self._save()
        logger.info(f"Added {len(new_chunks)} chunks to vector store")
        return len(new_chunks)

    def search(
        self,
        query: str,
        top_k: int = 5,
        document_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Semantic search over indexed chunks.

        Args:
            query: The search query string.
            top_k: Maximum number of chunks to return (1-20).
            document_filter: If set, only return chunks from this document_id.

        Returns:
            List of chunk dicts with added 'relevance_score' field.
        """
        if not _FAISS_AVAILABLE or self._index is None or self._index.ntotal == 0:
            return []

        top_k = max(1, min(top_k, 20))
        query_vec = self._embed([query])

        # Search more candidates when filtering
        k_search = min(top_k * 3 if document_filter else top_k,
                       self._index.ntotal)
        scores, indices = self._index.search(query_vec, k_search)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._metadata):
                continue
            meta = dict(self._metadata[idx])
            if document_filter and meta.get("document_id") != document_filter:
                continue
            meta["relevance_score"] = float(score)
            results.append(meta)
            if len(results) >= top_k:
                break

        return sorted(results, key=lambda x: x["relevance_score"], reverse=True)

    def get_indexed_documents(self) -> list[dict]:
        """Return unique documents currently indexed."""
        seen = {}
        for m in self._metadata:
            doc_id = m.get("document_id", "")
            if doc_id not in seen:
                seen[doc_id] = {
                    "document_id": doc_id,
                    "filename": m.get("filename", ""),
                    "chunk_count": 0,
                }
            seen[doc_id]["chunk_count"] += 1
        return list(seen.values())

    def delete_document(self, document_id: str) -> int:
        """
        Remove all chunks for a document. Rebuilds the FAISS index.
        Returns number of chunks removed.
        """
        if not _FAISS_AVAILABLE:
            return 0
        before = len(self._metadata)
        self._metadata = [m for m in self._metadata
                          if m.get("document_id") != document_id]
        removed = before - len(self._metadata)
        if removed > 0:
            self._rebuild_index()
        return removed

    def _rebuild_index(self) -> None:
        """Rebuild FAISS index from current metadata (needed after deletions)."""
        if not self._metadata:
            self._index = None
            self._save()
            return
        texts = [m["text"] for m in self._metadata]
        vectors = self._embed(texts)
        dim = vectors.shape[1]
        self._index = faiss.IndexFlatIP(dim)
        self._index.add(vectors)
        self._save()
        logger.info(f"Rebuilt index with {len(self._metadata)} chunks")

    @property
    def total_chunks(self) -> int:
        return len(self._metadata)

    @property
    def is_available(self) -> bool:
        return _FAISS_AVAILABLE and _ST_AVAILABLE
