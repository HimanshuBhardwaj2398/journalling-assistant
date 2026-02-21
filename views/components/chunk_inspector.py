"""Reusable chunk inspector component."""

from typing import List

import streamlit as st


def render_chunk_inspector(chunks: List, key_prefix: str = "ci"):
    """Render a paginated chunk inspector."""
    if not chunks:
        st.info("No chunks to display.")
        return

    total = len(chunks)
    ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([1, 2, 2, 1.25])

    with ctrl_col1:
        st.markdown(f"**{total} chunks**")

    with ctrl_col2:
        saved_idx = int(st.session_state.get(f"{key_prefix}_idx", 0))
        current_idx = _clamp_index(saved_idx, total)
        chunk_idx = st.number_input(
            "Go to chunk",
            min_value=0,
            max_value=total - 1,
            value=current_idx,
            step=1,
            key=f"{key_prefix}_nav",
        )
        st.session_state[f"{key_prefix}_idx"] = chunk_idx

    with ctrl_col3:
        filter_text = st.text_input(
            "Filter chunks",
            placeholder="Search chunk content...",
            key=f"{key_prefix}_filter",
        )

    with ctrl_col4:
        show_all = st.checkbox(
            "Show all",
            value=False,
            key=f"{key_prefix}_show_all",
        )

    if filter_text:
        filtered = [c for c in chunks if filter_text.lower() in c.chunk_text.lower()]
        if not filtered:
            st.warning(f"No chunks match '{filter_text}'")
            return
        st.caption(f"Showing {len(filtered)} of {total} chunks matching '{filter_text}'")
        display_chunks = filtered
    elif show_all:
        st.caption(f"Showing all {total} chunks")
        display_chunks = chunks
    else:
        selected = chunks[int(chunk_idx)]
        st.caption(
            f"Showing 1 of {total} chunks (selected chunk index: {selected.chunk_index})"
        )
        display_chunks = [selected]

    for chunk in display_chunks:
        _render_single_chunk(chunk)


def _render_single_chunk(chunk):
    """Render a single chunk with metadata and full content."""
    size = len(chunk.chunk_text)
    if size < 700:
        size_label = f"🟡 {size} chars (small)"
    elif size > 2000:
        size_label = f"🔴 {size} chars (large)"
    else:
        size_label = f"🟢 {size} chars"

    st.markdown(f"#### Chunk {chunk.chunk_index}")

    meta_col1, meta_col2, meta_col3 = st.columns(3)
    with meta_col1:
        st.markdown(f"**Index:** {chunk.chunk_index}")
    with meta_col2:
        st.markdown(f"**Size:** {size_label}")
    with meta_col3:
        st.markdown(f"**UUID:** `{chunk.uuid[:12]}...`")

    metadata = chunk.chunk_metadata or {}
    header_path = metadata.get("header_path", "")
    if not header_path:
        header_path = _legacy_header_path_from_metadata(metadata)
    if header_path:
        st.markdown(f"**Header path:** {header_path}")

    all_paths = metadata.get("all_header_paths", [])
    if all_paths:
        with st.expander("All header paths"):
            for path in all_paths:
                st.markdown(f"- `{path}`")

    if metadata:
        with st.expander("Raw metadata"):
            st.json(metadata)

    st.markdown("**Content:**")
    st.text(chunk.chunk_text)
    st.markdown("---")


def _clamp_index(value: int, total: int) -> int:
    """Clamp persisted index into valid chunk range."""
    if total <= 0:
        return 0
    if value < 0:
        return 0
    if value >= total:
        return total - 1
    return value


def _legacy_header_path_from_metadata(metadata: dict) -> str:
    """Build a fallback header path from legacy Header N metadata keys."""
    if not isinstance(metadata, dict):
        return ""

    headers = []
    for level in range(1, 7):
        value = metadata.get(f"Header {level}")
        if isinstance(value, str) and value.strip():
            headers.append(value.strip())

    return " > ".join(headers)
