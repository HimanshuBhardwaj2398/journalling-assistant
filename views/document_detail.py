"""Document detail page for deep inspection."""

import re
from typing import Any, Dict, List, Tuple

import streamlit as st

from db.crud import DocumentCRUD
from db.database import session_scope
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
        toc, toc_source = _get_effective_toc(doc, sorted_chunks)
        toc_headers = _flatten_toc(toc)
        has_toc = bool(toc_headers)

        tab_labels = []
        if has_toc:
            tab_labels.append("TOC Navigator")
        tab_labels.append("Side-by-Side")
        tab_labels.append("Chunk List")
        tabs = st.tabs(tab_labels)

        idx = 0
        if has_toc:
            with tabs[idx]:
                _render_toc_tab(
                    headers=toc_headers,
                    sorted_chunks=sorted_chunks,
                    doc_id=doc.id,
                    toc_source=toc_source,
                )
            idx += 1

        with tabs[idx]:
            _render_side_by_side_tab(doc, sorted_chunks, doc.id)
        idx += 1

        with tabs[idx]:
            render_chunk_inspector(sorted_chunks, key_prefix=f"detail_{doc.id}")


def _get_effective_toc(doc, sorted_chunks: List) -> Tuple[dict, str]:
    """Get TOC from document metadata or derive it from chunks as fallback."""
    metadata = doc.doc_metadata if isinstance(doc.doc_metadata, dict) else {}
    toc = metadata.get("table_of_contents", {})
    if _flatten_toc(toc):
        return toc, "document"

    fallback_toc = _build_toc_from_chunks(sorted_chunks)
    if _flatten_toc(fallback_toc):
        return fallback_toc, "chunks"

    return {}, "none"


def _render_toc_tab(
    headers: List[str],
    sorted_chunks: List,
    doc_id: int,
    toc_source: str,
):
    """Render TOC navigator and matching chunks."""
    left_col, right_col = st.columns([1, 2])
    with left_col:
        st.subheader("Table of Contents")
        if toc_source == "chunks":
            st.caption("Using TOC derived from chunk metadata.")

        if not headers:
            st.warning("No TOC headers found")
            return

        all_sections = "__ALL_SECTIONS__"
        selected_header = st.radio(
            "Select section",
            [all_sections, *headers],
            key=f"toc_header_select_{doc_id}",
            label_visibility="collapsed",
            format_func=lambda option: (
                f"All sections ({len(sorted_chunks)} chunks)" if option == all_sections else option
            ),
        )

    with right_col:
        if selected_header == all_sections:
            st.subheader("Chunks: All sections")
            matching = sorted_chunks
            st.caption("Showing every chunk in this document.")
        else:
            st.subheader(f"Chunks: {selected_header}")
            matching = [
                chunk for chunk in sorted_chunks if _chunk_matches_header(chunk, selected_header)
            ]

        if not matching:
            st.info("No chunks found under this header.")
            return

        if selected_header != all_sections:
            st.caption(f"Showing {len(matching)} of {len(sorted_chunks)} chunk(s)")
        render_chunk_inspector(matching, key_prefix=f"toc_{doc_id}")


def _flatten_toc(toc: dict, prefix: str = "") -> list:
    """Flatten nested TOC dict into selectable header paths."""
    headers = []
    if not isinstance(toc, dict):
        return headers

    entries = toc.get("entries")
    if isinstance(entries, list):
        entry_map = {
            entry.get("id"): entry
            for entry in entries
            if isinstance(entry, dict) and entry.get("id")
        }
        path_cache = {}

        def build_path(entry: dict) -> str:
            entry_id = entry.get("id")
            if entry_id in path_cache:
                return path_cache[entry_id]

            path_from_root = entry.get("path_from_root")
            if isinstance(path_from_root, str) and path_from_root.strip():
                normalized = _normalize_header_path(path_from_root)
                path_cache[entry_id] = normalized
                return normalized

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
        if key in {"entries", "text"}:
            continue

        full_path = f"{prefix} > {key}" if prefix else key
        headers.append(full_path)
        headers.extend(_flatten_toc(children, full_path))
    return headers


def _normalize_header_path(path: str) -> str:
    """Normalize header path separators/spaces to ' > ' format."""
    parts = [part.strip() for part in str(path).split(">") if part.strip()]
    return " > ".join(parts)


def _header_dict_to_path(metadata: Dict[str, Any]) -> str:
    """Build path from legacy Header N keys."""
    if not isinstance(metadata, dict):
        return ""

    levels = []
    for key, value in metadata.items():
        if not isinstance(value, str) or not value.strip():
            continue
        match = re.match(r"^Header\s+([1-6])$", str(key).strip())
        if match:
            levels.append((int(match.group(1)), value.strip()))

    if not levels:
        return ""

    levels.sort(key=lambda pair: pair[0])
    return " > ".join(value for _, value in levels)


def _extract_paths_from_chunk_metadata(metadata: Dict[str, Any]) -> List[str]:
    """Extract all possible header paths from new and legacy metadata shapes."""
    if not isinstance(metadata, dict):
        return []

    paths: List[str] = []

    def add_path(raw_path: Any):
        if not isinstance(raw_path, str):
            return
        normalized = _normalize_header_path(raw_path)
        if normalized and normalized not in paths:
            paths.append(normalized)

    all_header_paths = metadata.get("all_header_paths", [])
    if isinstance(all_header_paths, str):
        add_path(all_header_paths)
    elif isinstance(all_header_paths, list):
        for path in all_header_paths:
            add_path(path)

    add_path(metadata.get("header_path"))
    add_path(metadata.get("section_path"))

    all_headers = metadata.get("all_headers", [])
    if isinstance(all_headers, list):
        for header_dict in all_headers:
            add_path(_header_dict_to_path(header_dict))

    add_path(_header_dict_to_path(metadata))
    return paths


def _build_toc_from_chunks(sorted_chunks: List) -> dict:
    """Reconstruct TOC from chunk metadata when document-level TOC is missing."""
    entries = []
    seen_paths = {}  # path_from_root -> entry_id
    entry_count = 0

    for chunk in sorted_chunks:
        metadata = chunk.chunk_metadata or {}
        level_map = metadata.get("header_level_map", {})
        if not isinstance(level_map, dict):
            level_map = {}

        paths = _extract_paths_from_chunk_metadata(metadata)
        for path in paths:
            segments = [part.strip() for part in path.split(" > ") if part.strip()]
            if not segments:
                continue

            parent_path = ""
            for depth, segment in enumerate(segments, start=1):
                current_path = f"{parent_path} > {segment}" if parent_path else segment
                if current_path in seen_paths:
                    parent_path = current_path
                    continue

                raw_level = level_map.get(segment)
                level = raw_level if isinstance(raw_level, int) and raw_level > 0 else depth

                entry_id = f"h{level}_{entry_count}"
                parent_id = seen_paths.get(parent_path)
                entries.append(
                    {
                        "id": entry_id,
                        "level": level,
                        "text": segment,
                        "parent_id": parent_id,
                        "path_from_root": current_path,
                    }
                )
                seen_paths[current_path] = entry_id
                parent_path = current_path
                entry_count += 1

    text_lines = []
    for entry in entries:
        indent = "  " * (entry["level"] - 1)
        text_lines.append(f"{indent}{entry['text']}")

    return {
        "entries": entries,
        "text": "\n".join(text_lines),
    }


def _chunk_matches_header(chunk, header_path: str) -> bool:
    """Check whether chunk metadata belongs to selected header path."""
    metadata = chunk.chunk_metadata or {}
    paths = _extract_paths_from_chunk_metadata(metadata)

    for path in paths:
        if path == header_path or path.startswith(header_path + " > "):
            return True

    return False


def _render_side_by_side_tab(doc, sorted_chunks, doc_id: int):
    """Render markdown and chunk views side-by-side."""
    view_mode = st.radio(
        "View mode",
        ["Rendered", "Raw"],
        horizontal=True,
        key=f"side_by_side_view_mode_{doc_id}",
    )

    markdown_text = (doc.markdown or "").strip()
    markdown_source = "stored"
    if not markdown_text and sorted_chunks:
        markdown_text = "\n\n".join(chunk.chunk_text for chunk in sorted_chunks)
        markdown_source = "reconstructed"

    left_col, right_col = st.columns(2)
    with left_col:
        st.subheader("Original Markdown")
        if markdown_source == "reconstructed":
            st.caption("Document markdown missing. Showing reconstructed text from chunks.")

        if markdown_text:
            with st.container(height=600):
                if view_mode == "Rendered":
                    st.markdown(markdown_text)
                else:
                    st.code(markdown_text, language="markdown")
        else:
            st.warning("No markdown or chunk text available for this document.")

    with right_col:
        st.subheader(f"Chunks ({len(sorted_chunks)})")
        if not sorted_chunks:
            st.info("No chunks available for this document.")
            return

        with st.container(height=600):
            for chunk in sorted_chunks:
                size = len(chunk.chunk_text)
                st.caption(f"- Chunk {chunk.chunk_index} ({size} chars) -")
                if view_mode == "Rendered":
                    st.markdown(chunk.chunk_text)
                else:
                    st.code(chunk.chunk_text, language="markdown")
                st.markdown("---")
