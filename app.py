#!/usr/bin/env python3
"""
Meditation Database - Web Interface

Simple Streamlit app for ingesting and exploring meditation texts.

Usage:
    streamlit run app.py
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import streamlit as st
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from db.database import session_scope
from db.crud import DocumentCRUD, ChunkCRUD
from db.schema import DocumentStatus
from ingestion.orchestrator import IngestionOrchestrator
from ingestion.embed import VectorStoreConfig
import os

# ============================================================================
# PAGE CONFIGURATION
# ============================================================================

st.set_page_config(
    page_title="Meditation Database",
    page_icon="🧘",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# SESSION STATE
# ============================================================================

if 'ingestion_result' not in st.session_state:
    st.session_state.ingestion_result = None

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_orchestrator():
    """Initialize ingestion orchestrator."""
    db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL")
    return IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(
            collection_name="meditation_chunks",
            db_url=db_url,
        )
    )

async def ingest_document_async(source: str, title: str, description: str,
                                doc_type: str, category: str, tags: list):
    """Ingest document with metadata."""
    orchestrator = get_orchestrator()

    # Build metadata
    metadata = {}
    if doc_type:
        metadata["type"] = doc_type
    if category:
        metadata["category"] = category

    # Combine tags
    all_tags = tags.copy() if tags else []
    if doc_type:
        all_tags.append(f"type:{doc_type}")
    if category:
        all_tags.append(f"category:{category}")

    # Create document first with metadata
    with session_scope() as session:
        doc = DocumentCRUD(session).create_document(
            title=title,
            file_path=source,
            description=description,
            doc_metadata=metadata,
            tags=all_tags,
            status=DocumentStatus.PENDING,
        )
        doc_id = doc.id

    # Process through pipeline
    result = await orchestrator.process(source=doc_id, title=title)
    return result

def ingest_document(source: str, title: str, description: str,
                   doc_type: str, category: str, tags: list):
    """Wrapper to run async ingestion."""
    return asyncio.run(ingest_document_async(source, title, description,
                                            doc_type, category, tags))

# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.title("🧘 Meditation Database")
    st.markdown("---")

    page = st.radio(
        "Navigation",
        ["📥 Ingest New Document", "📚 Browse Database", "📊 Statistics"],
        label_visibility="collapsed"
    )

    st.markdown("---")
    st.caption("Built with Streamlit + LangChain + Voyage AI")

# ============================================================================
# PAGE: INGEST NEW DOCUMENT
# ============================================================================

if page == "📥 Ingest New Document":
    st.header("📥 Ingest New Document")
    st.markdown("Add a new meditation text to the database from a URL or PDF file.")

    # Source input
    source_type = st.radio("Source Type", ["URL", "File Path"], horizontal=True)

    if source_type == "URL":
        source = st.text_input(
            "Document URL",
            placeholder="https://example.com/article",
            help="Enter the full URL of the web page to ingest"
        )
    else:
        source = st.text_input(
            "File Path",
            placeholder="Books/my_document.pdf",
            help="Enter the path to a PDF file relative to project root"
        )

    # Metadata form
    col1, col2 = st.columns(2)

    with col1:
        title = st.text_input(
            "Title",
            placeholder="e.g., The Heart Sutra",
            help="Document title (required)"
        )

        doc_type = st.selectbox(
            "Document Type",
            ["", "ancient_text", "scientific_paper", "lecture",
             "commentary", "modern_teaching"],
            help="Type of meditation text"
        )

        category = st.text_input(
            "Category",
            placeholder="e.g., buddhism, neuroscience",
            help="Primary category or tradition"
        )

    with col2:
        description = st.text_area(
            "Description",
            placeholder="Brief description of the document...",
            help="Human-readable summary",
            height=100
        )

        tags_input = st.text_input(
            "Tags (comma-separated)",
            placeholder="mindfulness, vipassana, pali-canon",
            help="Additional tags for searchability"
        )

    # Parse tags
    tags = [t.strip() for t in tags_input.split(",")] if tags_input else []

    # Ingest button
    st.markdown("---")

    if st.button("🚀 Start Ingestion", type="primary", use_container_width=True):
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
                        tags=tags
                    )
                    st.session_state.ingestion_result = result
                except Exception as e:
                    st.error(f"Ingestion failed: {str(e)}")

    # Show results
    if st.session_state.ingestion_result:
        result = st.session_state.ingestion_result

        st.markdown("---")
        st.subheader("Ingestion Results")

        if result.get("success"):
            st.success("✅ Document successfully ingested!")

            col1, col2, col3 = st.columns(3)
            col1.metric("Document ID", result.get("document_id"))
            col2.metric("Chunks Created", result.get("chunk_count"))
            col3.metric("Status", "Completed")

        else:
            st.error("❌ Ingestion failed")

        # Stage details
        with st.expander("Pipeline Stage Details"):
            stages = result.get("stage_results", {})
            for stage_name, status in stages.items():
                icon = "✅" if status == "completed" else "❌"
                st.write(f"{icon} **{stage_name.replace('_', ' ').title()}**: {status}")

            if result.get("errors"):
                st.error("Errors:")
                for stage, error in result["errors"].items():
                    st.write(f"- {stage}: {error}")

# ============================================================================
# PAGE: BROWSE DATABASE
# ============================================================================

elif page == "📚 Browse Database":
    st.header("📚 Browse Database")

    # Filters
    col1, col2, col3 = st.columns(3)

    with col1:
        status_filter = st.selectbox(
            "Filter by Status",
            ["All", "COMPLETED", "FAILED", "PENDING", "PARSING", "CHUNKING", "EMBEDDING"]
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
            # Display documents
            for doc in docs:
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
                            st.write(f"**Metadata:**")
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

# ============================================================================
# PAGE: STATISTICS
# ============================================================================

elif page == "📊 Statistics":
    st.header("📊 Database Statistics")

    with session_scope() as session:
        crud = DocumentCRUD(session)
        chunk_crud = ChunkCRUD(session)

        docs = crud.get_all_documents()

        # Overall stats
        col1, col2, col3, col4 = st.columns(4)

        total_docs = len(docs)
        completed_docs = len([d for d in docs if d.status == DocumentStatus.COMPLETED])
        failed_docs = len([d for d in docs if d.status == DocumentStatus.FAILED])
        total_chunks = sum(len(d.document_chunks) for d in docs)

        col1.metric("Total Documents", total_docs)
        col2.metric("Completed", completed_docs)
        col3.metric("Failed", failed_docs)
        col4.metric("Total Chunks", total_chunks)

        st.markdown("---")

        # Status breakdown
        st.subheader("Documents by Status")
        status_counts = {}
        for doc in docs:
            status = doc.status.value
            status_counts[status] = status_counts.get(status, 0) + 1

        if status_counts:
            st.bar_chart(status_counts)

        st.markdown("---")

        # Type breakdown
        st.subheader("Documents by Type")
        type_counts = {}
        for doc in docs:
            doc_type = doc.doc_metadata.get("type", "unspecified")
            type_counts[doc_type] = type_counts.get(doc_type, 0) + 1

        if type_counts:
            st.bar_chart(type_counts)

        st.markdown("---")

        # Category breakdown
        st.subheader("Documents by Category")
        category_counts = {}
        for doc in docs:
            category = doc.doc_metadata.get("category", "unspecified")
            category_counts[category] = category_counts.get(category, 0) + 1

        if category_counts:
            st.bar_chart(category_counts)

        st.markdown("---")

        # Recent documents
        st.subheader("Recent Documents")
        recent = sorted(docs, key=lambda x: x.created_at, reverse=True)[:5]

        for doc in recent:
            status_icon = "✅" if doc.status == DocumentStatus.COMPLETED else "❌" if doc.status == DocumentStatus.FAILED else "⏳"
            st.write(f"{status_icon} **{doc.title}** - {doc.created_at.strftime('%Y-%m-%d %H:%M')}")
