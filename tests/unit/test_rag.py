"""Unit tests for RAG pipeline (document processing and vector store)."""
import pytest
import tempfile
import os
from pathlib import Path
from app.storage.document_processor import chunk_text, process_document, extract_text


class TestChunkText:
    def test_basic_chunking(self):
        text = " ".join([f"word{i}" for i in range(100)])
        chunks = chunk_text(text, chunk_size=20, overlap=5)
        assert len(chunks) > 1
        assert all(len(c.split()) <= 25 for c in chunks)

    def test_empty_text_returns_empty(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_overlap_creates_shared_words(self):
        text = " ".join([f"w{i}" for i in range(50)])
        chunks = chunk_text(text, chunk_size=10, overlap=3)
        # Consecutive chunks should share ~3 words
        if len(chunks) >= 2:
            end_of_first = set(chunks[0].split()[-5:])
            start_of_second = set(chunks[1].split()[:5])
            assert len(end_of_first & start_of_second) > 0

    def test_short_text_returns_single_chunk(self):
        text = "This is a short sentence."
        chunks = chunk_text(text, chunk_size=100, overlap=10)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_size_respected(self):
        text = " ".join(["word"] * 200)
        chunks = chunk_text(text, chunk_size=50, overlap=10)
        for chunk in chunks[:-1]:  # last chunk may be shorter
            assert len(chunk.split()) <= 55  # allow small overlap


class TestDocumentProcessor:
    def test_process_txt_file(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("This is a test document with some content about AI and machine learning.")
        chunks = process_document(str(txt_file), "test.txt", chunk_size=10, chunk_overlap=2)
        assert len(chunks) >= 1
        for c in chunks:
            assert "chunk_id" in c
            assert "document_id" in c
            assert "text" in c
            assert "filename" in c
            assert c["filename"] == "test.txt"

    def test_stable_chunk_ids(self, tmp_path):
        txt_file = tmp_path / "stable.txt"
        txt_file.write_text("Hello world this is a test document for ID stability.")
        chunks1 = process_document(str(txt_file), "stable.txt")
        chunks2 = process_document(str(txt_file), "stable.txt")
        # Same content → same IDs
        assert chunks1[0]["chunk_id"] == chunks2[0]["chunk_id"]
        assert chunks1[0]["document_id"] == chunks2[0]["document_id"]

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            process_document("/nonexistent/path/file.txt", "file.txt")

    def test_empty_file_raises(self, tmp_path):
        empty = tmp_path / "empty.txt"
        empty.write_text("")
        with pytest.raises(ValueError, match="No readable text"):
            process_document(str(empty), "empty.txt")

    def test_chunk_index_sequential(self, tmp_path):
        txt_file = tmp_path / "long.txt"
        txt_file.write_text(" ".join(["word"] * 300))
        chunks = process_document(str(txt_file), "long.txt", chunk_size=50, chunk_overlap=5)
        indices = [c["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))


class TestVectorStore:
    def test_add_and_search(self, tmp_path):
        try:
            from app.storage.vector_store import VectorStore
            vs = VectorStore(store_dir=str(tmp_path), embedding_model="all-MiniLM-L6-v2")
            if not vs.is_available:
                pytest.skip("FAISS/sentence-transformers not available")

            chunks = [
                {"chunk_id": "c1", "document_id": "d1", "text": "Quantum computing uses qubits.",
                 "filename": "quantum.txt", "chunk_index": 0},
                {"chunk_id": "c2", "document_id": "d1", "text": "Neural networks learn patterns.",
                 "filename": "ai.txt", "chunk_index": 1},
                {"chunk_id": "c3", "document_id": "d2", "text": "Python is a programming language.",
                 "filename": "python.txt", "chunk_index": 0},
            ]
            added = vs.add_chunks(chunks)
            assert added == 3

            results = vs.search("quantum computing", top_k=2)
            assert len(results) >= 1
            assert results[0]["chunk_id"] == "c1"
            assert "relevance_score" in results[0]

        except ImportError:
            pytest.skip("Dependencies not available")

    def test_duplicate_chunks_not_re_indexed(self, tmp_path):
        try:
            from app.storage.vector_store import VectorStore
            vs = VectorStore(store_dir=str(tmp_path), embedding_model="all-MiniLM-L6-v2")
            if not vs.is_available:
                pytest.skip("FAISS not available")

            chunk = [{"chunk_id": "dup1", "document_id": "d1",
                      "text": "Duplicate text.", "filename": "dup.txt", "chunk_index": 0}]
            added1 = vs.add_chunks(chunk)
            added2 = vs.add_chunks(chunk)
            assert added1 == 1
            assert added2 == 0  # duplicate skipped

        except ImportError:
            pytest.skip("Dependencies not available")

    def test_empty_search_returns_empty(self, tmp_path):
        try:
            from app.storage.vector_store import VectorStore
            vs = VectorStore(store_dir=str(tmp_path), embedding_model="all-MiniLM-L6-v2")
            if not vs.is_available:
                pytest.skip("FAISS not available")
            results = vs.search("anything", top_k=5)
            assert results == []
        except ImportError:
            pytest.skip("Dependencies not available")

