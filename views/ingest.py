"""
Ingest New Document page.

Provides UI for adding new meditation texts to the database.
"""

import tempfile
from pathlib import Path

import streamlit as st

from core.exceptions import DuplicateDocumentError
from services.ingestion_service import ingest_document
from db.database import session_scope
from db.crud import get_all_collections


def render():
    """Render the document ingestion page."""
    st.header("Ingest New Document")
    st.markdown("Add a new meditation text to the database from a URL or PDF file.")

    # Source input
    source_type = st.radio("Source Type", ["URL", "Upload File"], horizontal=True)

    source = None
    uploaded_file = None

    if source_type == "URL":
        source = st.text_input(
            "Document URL",
            placeholder="https://example.com/article",
            help="Enter the full URL of the web page to ingest",
        )
    else:
        uploaded_file = st.file_uploader(
            "Upload PDF",
            type=["pdf"],
            help="Select a PDF file to ingest",
        )

    # Metadata form
    col1, col2 = st.columns(2)

    with col1:
        title = st.text_input(
            "Title",
            placeholder="e.g., The Heart Sutra",
            help="Document title (required)",
        )

        doc_type = st.selectbox(
            "Document Type",
            ["", "ancient_text", "scientific_paper", "lecture", "commentary", "modern_teaching"],
            help="Type of meditation text",
        )

        category = st.text_input(
            "Category",
            placeholder="e.g., buddhism, neuroscience",
            help="Primary category or tradition",
        )

    with col2:
        description = st.text_area(
            "Description",
            placeholder="Brief description of the document...",
            help="Human-readable summary",
            height=100,
        )

        tags_input = st.text_input(
            "Tags (comma-separated)",
            placeholder="mindfulness, vipassana, pali-canon",
            help="Additional tags for searchability",
        )

    # Parse tags
    tags = [t.strip() for t in tags_input.split(",")] if tags_input else []

    # Collection selection
    st.markdown("---")
    col_header, col_refresh = st.columns([3, 1])
    with col_header:
        st.subheader("Collection")
    with col_refresh:
        if st.button("🔄 Refresh", key="refresh_collections"):
            st.session_state.pop("collections_cache", None)
            st.session_state.pop("collections_error", None)
            st.rerun()

    st.markdown("Choose which collection to store embeddings in.")

    # Fetch existing collections (cached to avoid repeated DB calls on every render)
    # Only cache successful fetches - failed fetches can be retried with refresh button
    if "collections_cache" not in st.session_state:
        try:
            with session_scope() as session:
                st.session_state.collections_cache = get_all_collections(session)
                st.session_state.pop("collections_error", None)  # Clear any previous error
        except Exception as e:
            st.session_state.collections_error = str(e)
            st.session_state.collections_cache = None  # Don't cache empty on failure

    # Show error if fetch failed
    if st.session_state.get("collections_error"):
        st.error(f"Failed to load collections: {st.session_state.collections_error}")
        st.info("Click 'Refresh' to retry, or create a new collection below.")

    existing_collections = st.session_state.get("collections_cache") or []

    # Add "Create New" option
    collection_options = existing_collections + ["+ Create New Collection"]

    selected_option = st.selectbox(
        "Select Collection",
        collection_options,
        index=0 if existing_collections else len(collection_options) - 1,
        help="Choose an existing collection or create a new one",
    )

    # Show text input if creating new collection
    if selected_option == "+ Create New Collection":
        new_collection_name = st.text_input(
            "New Collection Name",
            placeholder="e.g., Buddhist Discourses, Research Papers",
            help="Enter a name for the new collection (no spaces recommended)",
        )
        collection_name = new_collection_name.strip() if new_collection_name else ""
    else:
        collection_name = selected_option

    # Ingest button
    st.markdown("---")

    if st.button("Start Ingestion", type="primary", use_container_width=True):
        # Validate inputs
        if source_type == "URL" and not source:
            st.error("Please provide a source URL")
        elif source_type == "Upload File" and not uploaded_file:
            st.error("Please upload a PDF file")
        elif not title:
            st.error("Please provide a title")
        elif not collection_name:
            st.error("Please select or create a collection")
        else:
            with st.spinner("Processing document... This may take a few minutes."):
                try:
                    # Handle uploaded file by saving to temp location
                    if uploaded_file is not None:
                        suffix = Path(uploaded_file.name).suffix
                        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                            tmp.write(uploaded_file.getbuffer())
                            source = tmp.name

                    result = ingest_document(
                        source=source,
                        title=title,
                        description=description,
                        doc_type=doc_type,
                        category=category,
                        tags=tags,
                        collection_name=collection_name,
                    )
                    st.session_state.ingestion_result = result
                    # Clear collections cache so new collection appears
                    st.session_state.pop("collections_cache", None)
                except DuplicateDocumentError as e:
                    st.error("Duplicate Document Detected")
                    st.warning(str(e))
                except Exception as e:
                    st.error(f"Ingestion failed: {str(e)}")

    # Show results
    if st.session_state.get("ingestion_result"):
        result = st.session_state.ingestion_result

        st.markdown("---")
        st.subheader("Ingestion Results")

        if result.get("success"):
            st.success("Document successfully ingested!")

            col1, col2, col3 = st.columns(3)
            col1.metric("Document ID", result.get("document_id"))
            col2.metric("Chunks Created", result.get("chunk_count"))
            col3.metric("Status", "Completed")

        else:
            st.error("Ingestion failed")

        # Stage details
        with st.expander("Pipeline Stage Details"):
            stages = result.get("stage_results", {})
            for stage_name, status in stages.items():
                icon = "+" if status == "completed" else "x"
                st.write(f"{icon} **{stage_name.replace('_', ' ').title()}**: {status}")

            if result.get("errors"):
                st.error("Errors:")
                for stage, error in result["errors"].items():
                    st.write(f"- {stage}: {error}")
