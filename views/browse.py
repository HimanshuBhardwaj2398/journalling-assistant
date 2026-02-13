"""
Browse Database page.

Provides UI for exploring and managing documents in the database.
"""

import streamlit as st

from db.database import session_scope
from db.crud import DocumentCRUD
from db.schema import DocumentStatus
from services.collection_service import CollectionService


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

        # Actions section
        st.markdown("---")
        _render_action_controls(doc)


def _render_action_controls(doc):
    """Render action buttons (reprocess, delete) for a document."""
    # Check which action is pending confirmation
    pending_action = st.session_state.get("pending_action")
    pending_doc_id = st.session_state.get("pending_doc_id")

    # Show action buttons or confirmation
    btn_col1, btn_col2, msg_col = st.columns([1, 1, 2])

    with btn_col1:
        if pending_doc_id == doc.id and pending_action == "reprocess":
            # Show reprocess confirmation
            confirm_col, cancel_col = st.columns(2)
            with confirm_col:
                if st.button("Yes", key=f"confirm_reprocess_{doc.id}", type="primary"):
                    with st.spinner("Reprocessing..."):
                        service = CollectionService()
                        result = service.reprocess_document_sync(doc.id)

                    st.session_state.pending_action = None
                    st.session_state.pending_doc_id = None
                    if result.success:
                        st.success(
                            f"Reprocessed: {result.old_chunks_deleted} old chunks removed, "
                            f"{result.new_chunks_created} new chunks created"
                        )
                    else:
                        st.error(f"Reprocess failed: {result.error}")
                    st.rerun()
            with cancel_col:
                if st.button("No", key=f"cancel_reprocess_{doc.id}"):
                    st.session_state.pending_action = None
                    st.session_state.pending_doc_id = None
                    st.rerun()
        else:
            if st.button("Reprocess", key=f"reprocess_{doc.id}"):
                st.session_state.pending_action = "reprocess"
                st.session_state.pending_doc_id = doc.id
                st.rerun()

    with btn_col2:
        if pending_doc_id == doc.id and pending_action == "delete":
            # Show delete confirmation
            confirm_col, cancel_col = st.columns(2)
            with confirm_col:
                if st.button("Yes", key=f"confirm_del_{doc.id}", type="primary"):
                    service = CollectionService()
                    result = service.delete_document_complete_sync(doc.id)

                    st.session_state.pending_action = None
                    st.session_state.pending_doc_id = None
                    if result.success:
                        st.success(
                            f"Deleted: {result.chunks_deleted} chunks, "
                            f"{result.embeddings_deleted} embeddings"
                        )
                    else:
                        st.error(f"Delete failed: {result.error}")
                    st.rerun()
            with cancel_col:
                if st.button("No", key=f"cancel_del_{doc.id}"):
                    st.session_state.pending_action = None
                    st.session_state.pending_doc_id = None
                    st.rerun()
        else:
            if st.button("Delete", key=f"delete_{doc.id}", type="secondary"):
                st.session_state.pending_action = "delete"
                st.session_state.pending_doc_id = doc.id
                st.rerun()

    with msg_col:
        if pending_doc_id == doc.id:
            if pending_action == "reprocess":
                st.warning(
                    f"Reprocess '{doc.title}'? This will delete {len(doc.document_chunks)} "
                    f"existing chunks and re-chunk/re-embed the document."
                )
            elif pending_action == "delete":
                st.warning(
                    f"Delete '{doc.title}', {len(doc.document_chunks)} chunks, "
                    f"and all embeddings?"
                )
