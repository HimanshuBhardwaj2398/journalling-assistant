"""
Ingest New Document page.

Provides UI for adding new meditation texts to the database.
"""

import streamlit as st

from core.exceptions import DuplicateDocumentError
from services.ingestion_service import ingest_document


def render():
    """Render the document ingestion page."""
    st.header("Ingest New Document")
    st.markdown("Add a new meditation text to the database from a URL or PDF file.")

    # Source input
    source_type = st.radio("Source Type", ["URL", "File Path"], horizontal=True)

    if source_type == "URL":
        source = st.text_input(
            "Document URL",
            placeholder="https://example.com/article",
            help="Enter the full URL of the web page to ingest",
        )
    else:
        source = st.text_input(
            "File Path",
            placeholder="Books/my_document.pdf",
            help="Enter the path to a PDF file relative to project root",
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

    # Ingest button
    st.markdown("---")

    if st.button("Start Ingestion", type="primary", use_container_width=True):
        if not source:
            st.error("Please provide a source URL or file path")
        elif not title:
            st.error("Please provide a title")
        else:
            with st.spinner("Processing document... This may take a few minutes."):
                try:
                    result = ingest_document(
                        source=source,
                        title=title,
                        description=description,
                        doc_type=doc_type,
                        category=category,
                        tags=tags,
                    )
                    st.session_state.ingestion_result = result
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
