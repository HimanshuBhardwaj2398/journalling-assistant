"""
Browse Database page.

Provides UI for exploring and managing documents in the database.
"""

import streamlit as st

from db.database import session_scope
from db.crud import DocumentCRUD
from db.schema import DocumentStatus


def render():
    """Render the browse database page."""
    st.header("Browse Database")

    # Filters
    col1, col2, col3 = st.columns(3)

    with col1:
        status_filter = st.selectbox(
            "Filter by Status",
            ["All", "COMPLETED", "FAILED", "PENDING", "PARSING", "CHUNKING", "EMBEDDING"],
        )

    with col2:
        type_filter = st.text_input("Filter by Type", placeholder="e.g., ancient_text")

    with col3:
        category_filter = st.text_input("Filter by Category", placeholder="e.g., buddhism")

    # Get documents
    with session_scope() as session:
        crud = DocumentCRUD(session)

        if status_filter == "All":
            docs = crud.get_all_documents()
        else:
            status_enum = DocumentStatus[status_filter]
            docs = crud.get_documents_by_status(status_enum)

        # Apply metadata filters
        if type_filter:
            docs = [d for d in docs if d.doc_metadata.get("type") == type_filter]
        if category_filter:
            docs = [d for d in docs if d.doc_metadata.get("category") == category_filter]

        st.markdown(f"**Found {len(docs)} document(s)**")
        st.markdown("---")

        if not docs:
            st.info("No documents found. Ingest your first document to get started!")
        else:
            for doc in docs:
                _render_document_card(doc, session)


def _render_document_card(doc, session):
    """Render a single document card with details and actions."""
    with st.expander(f"**[{doc.id}] {doc.title}**", expanded=False):
        col1, col2 = st.columns([2, 1])

        with col1:
            st.write(f"**Status:** {doc.status.value}")
            st.write(f"**Source:** {doc.file_path}")

            if doc.description:
                st.write(f"**Description:** {doc.description}")

            if doc.tags:
                st.write(f"**Tags:** {', '.join(doc.tags)}")

            if doc.doc_metadata:
                st.write("**Metadata:**")
                st.json(doc.doc_metadata, expanded=False)

        with col2:
            st.metric("Chunks", len(doc.document_chunks))
            st.write(f"**Created:** {doc.created_at.strftime('%Y-%m-%d')}")
            st.write(f"**Updated:** {doc.updated_at.strftime('%Y-%m-%d')}")

        # Show chunk preview
        if doc.document_chunks:
            with st.expander("Preview Chunks"):
                for i, chunk in enumerate(doc.document_chunks[:3]):
                    st.markdown(f"**Chunk {i}** ({len(chunk.chunk_text)} chars)")
                    st.text(chunk.chunk_text[:200] + "...")

                if len(doc.document_chunks) > 3:
                    st.caption(f"... and {len(doc.document_chunks) - 3} more chunks")

        # Delete section
        st.markdown("---")
        _render_delete_controls(doc)


def _render_delete_controls(doc):
    """Render delete confirmation controls for a document."""
    delete_col1, delete_col2 = st.columns([1, 3])

    with delete_col1:
        if st.session_state.get("delete_confirm") == doc.id:
            # Show confirmation buttons
            confirm_col, cancel_col = st.columns(2)
            with confirm_col:
                if st.button("Yes", key=f"confirm_del_{doc.id}", type="primary"):
                    with session_scope() as del_session:
                        del_crud = DocumentCRUD(del_session)
                        chunk_count = len(doc.document_chunks)
                        if del_crud.delete_document(doc.id):
                            st.session_state.delete_confirm = None
                            st.success(f"Deleted document and {chunk_count} chunks")
                            st.rerun()
            with cancel_col:
                if st.button("No", key=f"cancel_del_{doc.id}"):
                    st.session_state.delete_confirm = None
                    st.rerun()
        else:
            if st.button("Delete", key=f"delete_{doc.id}", type="secondary"):
                st.session_state.delete_confirm = doc.id
                st.rerun()

    with delete_col2:
        if st.session_state.get("delete_confirm") == doc.id:
            st.warning(f"Delete '{doc.title}' and all {len(doc.document_chunks)} chunks?")
