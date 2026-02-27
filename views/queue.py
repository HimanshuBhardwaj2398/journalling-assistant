"""
Processing Queue page.

Provides UI for processing pending documents and retrying failed ones.
"""

import streamlit as st

from db.crud import DocumentCRUD
from db.database import session_scope
from db.schema import DocumentStatus
from services.ingestion_service import process_document_by_id


def render():
    """Render the processing queue page."""
    st.header("Processing Queue")
    st.markdown("Process pending documents or retry failed ones.")

    with session_scope() as session:
        crud = DocumentCRUD(session)

        # Get pending and failed documents
        pending_docs = crud.get_documents_by_status(DocumentStatus.PENDING)
        failed_docs = crud.get_documents_by_status(DocumentStatus.FAILED)

        # Also get in-progress documents
        parsing_docs = crud.get_documents_by_status(DocumentStatus.PARSING)
        chunking_docs = crud.get_documents_by_status(DocumentStatus.CHUNKING)
        embedding_docs = crud.get_documents_by_status(DocumentStatus.EMBEDDING)
        in_progress = parsing_docs + chunking_docs + embedding_docs

        # Summary metrics
        col1, col2, col3 = st.columns(3)
        col1.metric("Pending", len(pending_docs))
        col2.metric("In Progress", len(in_progress))
        col3.metric("Failed", len(failed_docs))

        st.markdown("---")

        # Pending Documents Section
        if pending_docs:
            _render_pending_section(pending_docs)
        else:
            st.info("No pending documents.")

        # In-Progress Documents Section
        if in_progress:
            _render_in_progress_section(in_progress)

        # Failed Documents Section
        if failed_docs:
            _render_failed_section(failed_docs)
        elif not pending_docs and not in_progress:
            st.success("All documents have been processed!")


def _render_pending_section(pending_docs: list):
    """Render the pending documents section."""
    st.subheader("Pending Documents")
    st.markdown("Documents waiting to be processed.")

    for doc in pending_docs:
        col1, col2, col3 = st.columns([3, 1, 1])

        with col1:
            st.markdown(f"**[{doc.id}] {doc.title}**")
            st.caption(f"Source: {doc.file_path}")

        with col2:
            st.markdown(f"Created: {doc.created_at.strftime('%Y-%m-%d')}")

        with col3:
            if st.button("Process", key=f"process_{doc.id}", type="primary"):
                st.session_state.last_processed_id = doc.id

    # Process document if button was clicked
    if st.session_state.get("last_processed_id"):
        doc_id = st.session_state.last_processed_id
        st.markdown("---")

        with st.status(f"Processing document {doc_id}...", expanded=True) as status:
            st.write("Starting pipeline...")
            st.session_state.processing_status[doc_id] = {
                "status": "processing",
                "message": "Pipeline started",
            }

            try:
                result = process_document_by_id(doc_id)

                if result.get("success"):
                    st.write("+ Parsing complete")
                    st.write("+ Chunking complete")
                    st.write("+ Embedding complete")
                    st.write("+ Database persistence complete")
                    status.update(label="Processing complete!", state="complete")

                    st.session_state.processing_status[doc_id] = {
                        "status": "completed",
                        "message": f"Created {result.get('chunk_count', 0)} chunks",
                    }

                    st.success(
                        f"Document processed successfully! Created {result.get('chunk_count', 0)} chunks."
                    )
                else:
                    errors = result.get("errors", {})
                    status.update(label="Processing failed", state="error")

                    st.session_state.processing_status[doc_id] = {
                        "status": "failed",
                        "message": str(errors),
                    }

                    st.error(f"Processing failed: {errors}")

            except Exception as e:
                status.update(label="Processing failed", state="error")
                st.session_state.processing_status[doc_id] = {
                    "status": "failed",
                    "message": str(e),
                }
                st.error(f"Error: {str(e)}")

            finally:
                st.session_state.last_processed_id = None

    st.markdown("---")


def _render_in_progress_section(in_progress: list):
    """Render the in-progress documents section."""
    st.subheader("In Progress")
    st.markdown("Documents currently being processed.")

    for doc in in_progress:
        status_emoji = {
            DocumentStatus.PARSING: "[parsing]",
            DocumentStatus.CHUNKING: "[chunking]",
            DocumentStatus.EMBEDDING: "[embedding]",
        }.get(doc.status, "[processing]")

        col1, col2 = st.columns([3, 1])

        with col1:
            st.markdown(f"**[{doc.id}] {doc.title}**")
            st.caption(f"Source: {doc.file_path}")

        with col2:
            st.markdown(f"{status_emoji} {doc.status.value.upper()}")

    st.markdown("---")


def _render_failed_section(failed_docs: list):
    """Render the failed documents section."""
    st.subheader("Failed Documents")
    st.markdown(
        "Documents that failed processing. Click retry to attempt again or delete to remove."
    )

    for doc in failed_docs:
        with st.expander(f"**[{doc.id}] {doc.title}**", expanded=False):
            col1, col2 = st.columns([3, 1])

            with col1:
                st.write(f"**Source:** {doc.file_path}")
                st.write(f"**Failed at:** {doc.updated_at.strftime('%Y-%m-%d %H:%M')}")

                if doc.status_details:
                    st.error(f"**Error:** {doc.status_details}")

            with col2:
                if st.button("Retry", key=f"retry_{doc.id}", type="secondary"):
                    # Reset status to PENDING and trigger reprocessing
                    with session_scope() as retry_session:
                        DocumentCRUD(retry_session).update_status(
                            document_id=doc.id,
                            status=DocumentStatus.PENDING,
                            status_details=None,
                        )
                    st.session_state.last_processed_id = doc.id
                    st.rerun()

                if st.button("Delete", key=f"del_failed_{doc.id}", type="secondary"):
                    with session_scope() as del_session:
                        if DocumentCRUD(del_session).delete_document(doc.id):
                            st.success(f"Deleted document {doc.id}")
                            st.rerun()
