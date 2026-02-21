"""Document detail page for deep inspection."""

import streamlit as st

from db.database import session_scope
from db.crud import DocumentCRUD
from views.components.chunk_inspector import render_chunk_inspector


def render(doc_id: int):
    """Render detail page for a single document."""
    if st.button("<- Back to Browse"):
        st.session_state.pop("selected_doc_id", None)
        st.rerun()

    with session_scope() as session:
        crud = DocumentCRUD(session)
        doc = crud.get_document_by_id(doc_id)

        if not doc:
            st.error(f"Document {doc_id} not found")
            return

        st.header(doc.title)
        col1, col2, col3 = st.columns(3)
        col1.metric("Status", doc.status.value)
        col2.metric("Chunks", len(doc.document_chunks))
        col3.metric("ID", doc.id)

        st.markdown("---")

        sorted_chunks = sorted(doc.document_chunks, key=lambda c: c.chunk_index)
        has_toc = bool(doc.doc_metadata and doc.doc_metadata.get("table_of_contents"))

        tab_labels = []
        if has_toc:
            tab_labels.append("TOC Navigator")
        tab_labels.append("Side-by-Side")
        tab_labels.append("Chunk List")
        tabs = st.tabs(tab_labels)

        idx = 0
        if has_toc:
            with tabs[idx]:
                _render_toc_tab(doc, sorted_chunks, doc.id)
            idx += 1

        with tabs[idx]:
            _render_side_by_side_tab(doc, sorted_chunks, doc.id)
        idx += 1

        with tabs[idx]:
            render_chunk_inspector(sorted_chunks, key_prefix=f"detail_{doc.id}")


def _render_toc_tab(doc, sorted_chunks, doc_id: int):
    """Render TOC navigator and matching chunks."""
    toc = doc.doc_metadata.get("table_of_contents", {})

    left_col, right_col = st.columns([1, 2])
    with left_col:
        st.subheader("Table of Contents")
        headers = _flatten_toc(toc)
        if not headers:
            st.warning("No TOC headers found")
            return

        selected_header = st.radio(
            "Select section",
            headers,
            key=f"toc_header_select_{doc_id}",
            label_visibility="collapsed",
        )

    with right_col:
        st.subheader(f"Chunks: {selected_header}")
        matching = [
            chunk for chunk in sorted_chunks
            if _chunk_matches_header(chunk, selected_header)
        ]
        if not matching:
            st.info("No chunks found under this header.")
            return

        st.caption(f"{len(matching)} chunk(s)")
        render_chunk_inspector(matching, key_prefix=f"toc_{doc_id}")


def _flatten_toc(toc: dict, prefix: str = "") -> list:
    """Flatten nested TOC dict into selectable header paths."""
    headers = []
    if not isinstance(toc, dict):
        return headers

    entries = toc.get("entries")
    if isinstance(entries, list):
        entry_map = {
            entry.get("id"): entry for entry in entries
            if isinstance(entry, dict) and entry.get("id")
        }
        path_cache = {}

        def build_path(entry: dict) -> str:
            entry_id = entry.get("id")
            if entry_id in path_cache:
                return path_cache[entry_id]

            path_from_root = entry.get("path_from_root")
            if isinstance(path_from_root, str) and path_from_root:
                path_cache[entry_id] = path_from_root
                return path_from_root

            text = (entry.get("text") or "").strip()
            parent_id = entry.get("parent_id")
            parent = entry_map.get(parent_id)
            if parent:
                parent_path = build_path(parent)
                full_path = f"{parent_path} > {text}" if parent_path else text
            else:
                full_path = text

            path_cache[entry_id] = full_path
            return full_path

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            full_path = build_path(entry)
            if full_path and full_path not in headers:
                headers.append(full_path)
        return headers

    for key, children in toc.items():
        full_path = f"{prefix} > {key}" if prefix else key
        headers.append(full_path)
        headers.extend(_flatten_toc(children, full_path))
    return headers


def _chunk_matches_header(chunk, header_path: str) -> bool:
    """Check whether chunk metadata belongs to selected header path."""
    metadata = chunk.chunk_metadata or {}
    all_paths = metadata.get("all_header_paths", [])
    for path in all_paths:
        if path == header_path or path.startswith(header_path + " > "):
            return True

    current = metadata.get("header_path", "")
    return current == header_path or current.startswith(header_path + " > ")


def _render_side_by_side_tab(doc, sorted_chunks, doc_id: int):
    """Render markdown and chunk views side-by-side."""
    view_mode = st.radio(
        "View mode",
        ["Rendered", "Raw"],
        horizontal=True,
        key=f"side_by_side_view_mode_{doc_id}",
    )

    left_col, right_col = st.columns(2)
    with left_col:
        st.subheader("Original Markdown")
        if doc.markdown:
            if view_mode == "Rendered":
                with st.container(height=600):
                    st.markdown(doc.markdown)
            else:
                st.code(doc.markdown, language="markdown")
        else:
            st.warning("No markdown stored for this document.")

    with right_col:
        st.subheader(f"Chunks ({len(sorted_chunks)})")
        with st.container(height=600):
            for chunk in sorted_chunks:
                size = len(chunk.chunk_text)
                st.caption(f"- Chunk {chunk.chunk_index} ({size} chars) -")
                if view_mode == "Rendered":
                    st.markdown(chunk.chunk_text)
                else:
                    st.code(chunk.chunk_text, language="markdown")
                st.markdown("---")
