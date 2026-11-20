"""Document Upload & RAG page."""
import json
import streamlit as st
from pathlib import Path
from app.config.settings import get_settings
from app.storage.document_processor import process_document
from app.storage.vector_store import VectorStore
from app.security.guardrails import validate_file_upload, GuardrailViolation


def render():
    st.header("📄 Document Upload & RAG")
    settings = get_settings()
    vs = VectorStore(store_dir=settings.vector_store_dir,
                     embedding_model=settings.embedding_model)

    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("Upload Documents")
        uploaded = st.file_uploader(
            "Upload PDF, TXT, DOCX, or CSV",
            type=["pdf", "txt", "docx", "md", "csv"],
            accept_multiple_files=True,
        )

        if uploaded:
            for f in uploaded:
                try:
                    safe_name, ftype = validate_file_upload(
                        f.name, len(f.getvalue()),
                        max_size_mb=settings.max_file_size_mb,
                    )
                    save_path = Path(settings.uploads_dir) / safe_name
                    with open(save_path, "wb") as fp:
                        fp.write(f.getvalue())

                    with st.spinner(f"Processing {safe_name}…"):
                        chunks = process_document(
                            str(save_path), safe_name,
                            chunk_size=settings.chunk_size,
                            chunk_overlap=settings.chunk_overlap,
                        )
                        added = vs.add_chunks(chunks)

                    if added > 0:
                        st.success(f"✅ Indexed {safe_name}: {added} chunks added")
                    else:
                        st.info(f"ℹ️ {safe_name}: already indexed (duplicate)")

                except GuardrailViolation as e:
                    st.error(f"❌ {f.name}: {e}")
                except Exception as exc:
                    st.error(f"❌ Error processing {f.name}: {exc}")

    with col2:
        st.subheader("Indexed Documents")
        docs = vs.get_indexed_documents()
        if docs:
            for d in docs:
                st.markdown(
                    f"📄 **{d['filename']}**  \n"
                    f"Chunks: {d['chunk_count']}  \n"
                    f"ID: `{d['document_id']}`"
                )
                if st.button(f"🗑️ Delete", key=f"del_{d['document_id']}"):
                    removed = vs.delete_document(d["document_id"])
                    st.success(f"Removed {removed} chunks")
                    st.rerun()
        else:
            st.info("No documents indexed yet.")
        st.metric("Total chunks", vs.total_chunks)
        st.metric("FAISS available", "✅" if vs.is_available else "❌")

    st.divider()
    st.subheader("Test Retrieval")
    q = st.text_input("Ask a question about your documents", placeholder="What is…")
    top_k = st.slider("Top K", 1, 10, settings.retrieval_top_k)

    if st.button("🔍 Retrieve", disabled=not q.strip()):
        if not vs.is_available:
            st.error("FAISS not available. Install faiss-cpu.")
        else:
            chunks = vs.search(q, top_k=top_k)
            if chunks:
                st.success(f"Found {len(chunks)} chunks")
                for c in chunks:
                    with st.expander(
                        f"📄 {c.get('filename')} | chunk {c.get('chunk_index')} "
                        f"| score {c.get('relevance_score',0):.3f}"
                    ):
                        st.markdown(f"> {c.get('text','')[:600]}")
            else:
                st.warning("No relevant chunks found. Upload documents first.")

