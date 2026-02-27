"""
Statistics page.

Provides UI for viewing database statistics and analytics.
"""

import streamlit as st

from db.crud import DocumentCRUD
from db.database import session_scope
from db.schema import DocumentStatus


def render():
    """Render the statistics page."""
    st.header("Database Statistics")

    with session_scope() as session:
        crud = DocumentCRUD(session)

        docs = crud.get_all_documents()

        # Overall stats
        _render_overview_metrics(docs)

        st.markdown("---")

        # Status breakdown
        _render_status_chart(docs)

        st.markdown("---")

        # Type breakdown
        _render_type_chart(docs)

        st.markdown("---")

        # Category breakdown
        _render_category_chart(docs)

        st.markdown("---")

        # Recent documents
        _render_recent_documents(docs)


def _render_overview_metrics(docs: list):
    """Render overview metrics row."""
    col1, col2, col3, col4, col5 = st.columns(5)

    total_docs = len(docs)
    pending_docs = len([d for d in docs if d.status == DocumentStatus.PENDING])
    completed_docs = len([d for d in docs if d.status == DocumentStatus.COMPLETED])
    failed_docs = len([d for d in docs if d.status == DocumentStatus.FAILED])
    total_chunks = sum(len(d.document_chunks) for d in docs)

    col1.metric("Total Documents", total_docs)
    col2.metric("Pending", pending_docs)
    col3.metric("Completed", completed_docs)
    col4.metric("Failed", failed_docs)
    col5.metric("Total Chunks", total_chunks)


def _render_status_chart(docs: list):
    """Render documents by status chart."""
    st.subheader("Documents by Status")
    status_counts = {}
    for doc in docs:
        status = doc.status.value
        status_counts[status] = status_counts.get(status, 0) + 1

    if status_counts:
        st.bar_chart(status_counts)


def _render_type_chart(docs: list):
    """Render documents by type chart."""
    st.subheader("Documents by Type")
    type_counts = {}
    for doc in docs:
        doc_type = doc.doc_metadata.get("type", "unspecified")
        type_counts[doc_type] = type_counts.get(doc_type, 0) + 1

    if type_counts:
        st.bar_chart(type_counts)


def _render_category_chart(docs: list):
    """Render documents by category chart."""
    st.subheader("Documents by Category")
    category_counts = {}
    for doc in docs:
        category = doc.doc_metadata.get("category", "unspecified")
        category_counts[category] = category_counts.get(category, 0) + 1

    if category_counts:
        st.bar_chart(category_counts)


def _render_recent_documents(docs: list):
    """Render recent documents list."""
    st.subheader("Recent Documents")
    recent = sorted(docs, key=lambda x: x.created_at, reverse=True)[:5]

    for doc in recent:
        if doc.status == DocumentStatus.COMPLETED:
            status_icon = "[completed]"
        elif doc.status == DocumentStatus.FAILED:
            status_icon = "[failed]"
        else:
            status_icon = "[pending]"
        st.write(f"{status_icon} **{doc.title}** - {doc.created_at.strftime('%Y-%m-%d %H:%M')}")
