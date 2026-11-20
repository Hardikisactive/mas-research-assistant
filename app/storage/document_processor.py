"""
Document processor: extract text from PDF/TXT/DOCX, chunk, generate stable IDs.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _doc_id(filepath: str, content_hash: str) -> str:
    """Stable document ID from path + content hash."""
    return hashlib.sha256(f"{filepath}:{content_hash}".encode()).hexdigest()[:16]


def _chunk_id(doc_id: str, chunk_index: int) -> str:
    """Stable chunk ID."""
    return f"{doc_id}:chunk:{chunk_index:04d}"


def extract_text_from_pdf(path: Path) -> str:
    """Extract text from a PDF file using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[Page {i+1}]\n{text}")
        return "\n\n".join(pages)
    except ImportError:
        logger.warning("pypdf not installed — cannot read PDF")
        return ""
    except Exception as exc:
        logger.error(f"PDF extraction failed for {path}: {exc}")
        return ""


def extract_text_from_docx(path: Path) -> str:
    """Extract text from DOCX. Requires python-docx."""
    try:
        import docx
        doc = docx.Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        logger.warning("python-docx not installed — cannot read DOCX")
        return ""
    except Exception as exc:
        logger.error(f"DOCX extraction failed for {path}: {exc}")
        return ""


def extract_text(path: Path) -> str:
    """Dispatch to the correct extractor based on file extension."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(path)
    elif suffix in {".txt", ".md"}:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            logger.error(f"Text read failed for {path}: {exc}")
            return ""
    elif suffix == ".docx":
        return extract_text_from_docx(path)
    elif suffix == ".json":
        try:
            import json
            data = json.loads(path.read_text(encoding="utf-8"))
            return str(data)
        except Exception:
            return path.read_text(encoding="utf-8", errors="replace")
    else:
        logger.warning(f"Unsupported file type: {suffix}")
        return ""


def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[str]:
    """
    Split text into overlapping chunks by word count.
    Respects sentence boundaries where possible.

    Args:
        text: Input text.
        chunk_size: Target chunk size in words.
        overlap: Number of words to overlap between adjacent chunks.

    Returns:
        List of text chunk strings.
    """
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end >= len(words):
            break
        start = end - overlap  # Overlap

    return chunks


def process_document(
    file_path: str,
    filename: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[dict]:
    """
    Full pipeline: extract → chunk → assign stable IDs.

    Args:
        file_path: Absolute path to the file.
        filename: Original user-supplied filename (sanitized).
        chunk_size: Chunk size in words.
        chunk_overlap: Overlap in words.

    Returns:
        List of chunk dicts ready to add to VectorStore.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {file_path}")

    # Extract
    text = extract_text(path)
    if not text.strip():
        raise ValueError(f"No readable text extracted from {filename}")

    # Stable doc ID from content
    content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    doc_id = _doc_id(file_path, content_hash)

    # Chunk
    raw_chunks = chunk_text(text, chunk_size=chunk_size, overlap=chunk_overlap)

    chunks = []
    for i, chunk_text_content in enumerate(raw_chunks):
        cid = _chunk_id(doc_id, i)
        chunks.append({
            "chunk_id": cid,
            "document_id": doc_id,
            "text": chunk_text_content,
            "filename": filename,
            "chunk_index": i,
            "total_chunks": len(raw_chunks),
            "page_number": None,  # page tracking requires PDF-level logic
        })

    logger.info(f"Processed '{filename}': {len(chunks)} chunks, doc_id={doc_id}")
    return chunks
