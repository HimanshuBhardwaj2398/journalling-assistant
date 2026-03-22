"""RAG playground page for retrieval testing and grounded answer inspection."""

from __future__ import annotations

import re
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import streamlit as st

from db.crud import DocumentCRUD
from db.database import session_scope
from db.schema import DocumentStatus
from retrieval.answering import AnswerResponse, GroundedAnswerService
from retrieval.query import RetrievalEngine, RetrievalStrategy, SearchResponse, SearchResult
from views.components.chunk_inspector import render_chunk_inspector

SEARCH_STATE_KEY = "rag_last_search"
ANSWER_STATE_KEY = "rag_last_answer"


@st.cache_resource(show_spinner=False)
def _get_retrieval_engine() -> RetrievalEngine:
    """Build and cache the retrieval engine for the session."""
    return RetrievalEngine()


@st.cache_data(ttl=30, show_spinner=False)
def _load_completed_documents() -> list[dict[str, Any]]:
    """Fetch completed documents for optional post-search filtering."""
    with session_scope() as session:
        docs = DocumentCRUD(session).get_documents_by_status(DocumentStatus.COMPLETED)

    return [
        {
            "id": int(doc.id),
            "title": doc.title,
            "label": f"[{doc.id}] {doc.title}",
        }
        for doc in docs
    ]


def _inject_styles() -> None:
    """Inject page-local styles."""
    st.markdown(
        """
        <style>
        .rag-banner {
            border: 1px solid #d1d5db;
            background: linear-gradient(135deg, #f8fafc 0%, #fefce8 100%);
            border-radius: 14px;
            padding: 14px 16px;
            margin-bottom: 12px;
        }
        .rag-banner p {
            margin: 0;
            color: #1f2937;
            font-size: 0.96rem;
        }
        .rag-note {
            color: #4b5563;
            font-size: 0.9rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _strategy_label(strategy: RetrievalStrategy) -> str:
    """Human-friendly label for a retrieval strategy."""
    labels = {
        RetrievalStrategy.SIMILARITY: "Similarity",
        RetrievalStrategy.MMR: "MMR",
        RetrievalStrategy.THRESHOLD: "Threshold",
        RetrievalStrategy.HYBRID: "Hybrid",
    }
    return labels[strategy]


def _format_score(score: float | None) -> str:
    """Format search scores for UI display."""
    if score is None:
        return "n/a"
    return f"{score:.4f}"


def _extract_header_paths(metadata: dict | None) -> list[str]:
    """Extract normalized header paths from chunk metadata."""
    if not isinstance(metadata, dict):
        return []

    paths: list[str] = []

    def add(raw: object) -> None:
        if not isinstance(raw, str):
            return
        cleaned = " > ".join(part.strip() for part in raw.split(">") if part.strip())
        if cleaned and cleaned not in paths:
            paths.append(cleaned)

    all_header_paths = metadata.get("all_header_paths", [])
    if isinstance(all_header_paths, str):
        add(all_header_paths)
    elif isinstance(all_header_paths, list):
        for path in all_header_paths:
            add(path)

    add(metadata.get("header_path"))
    add(metadata.get("section_path"))

    if not paths:
        legacy_headers = []
        for level in range(1, 7):
            value = metadata.get(f"Header {level}")
            if isinstance(value, str) and value.strip():
                legacy_headers.append(value.strip())
        if legacy_headers:
            paths.append(" > ".join(legacy_headers))

    return paths


def _primary_header_path(result: SearchResult) -> str:
    """Return the main header-path summary for a search result."""
    paths = _extract_header_paths(result.metadata)
    if not paths:
        return "(no header path)"
    if len(paths) == 1:
        return paths[0]
    return f"{paths[0]} (+{len(paths) - 1} more)"


def _build_result_rows(response: SearchResponse) -> list[dict[str, Any]]:
    """Build compact rows for the search result table."""
    rows: list[dict[str, Any]] = []
    for result in response.results:
        rows.append(
            {
                "Rank": result.rank,
                "Score": _format_score(result.score),
                "Source": result.source_title or "Unknown source",
                "Doc ID": result.document_id or "-",
                "Chunk": result.chunk_index if result.chunk_index is not None else "-",
                "Header Path": _primary_header_path(result),
                "Preview": result.text[:160].replace("\n", " "),
            }
        )
    return rows


def _to_chunk_like_objects(results: list[SearchResult]) -> list[SimpleNamespace]:
    """Adapt search results for reuse in the chunk inspector component."""
    chunk_like_objects: list[SimpleNamespace] = []
    for result in results:
        chunk_like_objects.append(
            SimpleNamespace(
                uuid=result.chunk_uuid or f"result-{result.rank}",
                chunk_index=result.chunk_index if result.chunk_index is not None else result.rank - 1,
                chunk_text=result.text,
                chunk_metadata=result.metadata,
            )
        )
    return chunk_like_objects


def _citation_labels_in_answer(answer: str) -> set[str]:
    """Extract citation labels like [1] or [2] from answer text."""
    return {f"[{match}]" for match in re.findall(r"\[(\d+)\]", answer or "")}


def _search_trace_to_dict(response: SearchResponse) -> dict[str, Any]:
    """Convert the search response into a JSON-friendly trace dict."""
    trace = response.trace
    if trace is None:
        return {
            "query": response.query,
            "strategy": response.strategy.value,
            "total_results": response.total_results,
        }

    return {
        "query": response.query,
        "strategy": response.strategy.value,
        "collection_name": trace.collection_name,
        "embedding_model": trace.embedding_model,
        "requested_k": trace.requested_k,
        "fetch_k": trace.fetch_k,
        "score_threshold": trace.score_threshold,
        "started_at": trace.started_at,
        "duration_ms": round(trace.duration_ms, 2),
        "total_results": response.total_results,
        "bm25_chunk_count": trace.bm25_chunk_count,
        "notes": trace.notes,
    }


def _answer_trace_to_dict(answer_response: AnswerResponse) -> dict[str, Any]:
    """Convert answer trace metadata into a JSON-friendly payload."""
    return {
        "model_id": answer_response.trace.model_id,
        "context_chunk_count": answer_response.trace.context_chunk_count,
        "context_char_count": answer_response.trace.context_char_count,
        "duration_ms": round(answer_response.trace.duration_ms, 2),
    }


def _apply_post_filter(
    response: SearchResponse,
    allowed_document_ids: list[int],
) -> SearchResponse:
    """Apply UI-level document filtering without mutating the original response."""
    if not allowed_document_ids:
        return response

    filtered_results = [
        result for result in response.results if result.document_id in set(allowed_document_ids)
    ]
    filtered_response = replace(response, results=filtered_results)
    filtered_response.total_results = len(filtered_results)
    if filtered_response.trace is not None:
        filtered_response.trace.total_results = len(filtered_results)
        filtered_response.trace.notes.append(
            "Results were post-filtered in the UI to the selected document IDs."
        )
    return filtered_response


def _open_document_detail(document_id: int) -> None:
    """Jump to the existing document detail page via sidebar navigation state."""
    st.session_state.selected_doc_id = document_id
    st.session_state.nav_page = "Browse Database"
    st.rerun()


def _render_result_cards(results: list[SearchResult]) -> None:
    """Render per-result cards with full content and navigation."""
    for result in results:
        source_title = result.source_title or "Unknown source"
        chunk_label = result.chunk_index if result.chunk_index is not None else "?"
        expander_label = (
            f"#{result.rank} · {source_title} · chunk {chunk_label} · score {_format_score(result.score)}"
        )
        with st.expander(expander_label, expanded=(result.rank == 1)):
            meta_col1, meta_col2, meta_col3 = st.columns(3)
            meta_col1.metric("Rank", result.rank)
            meta_col2.metric("Score", _format_score(result.score))
            meta_col3.metric("Chunk", str(chunk_label))

            st.markdown(f"**Source:** {source_title}")
            if result.document_id is not None:
                if st.button("Open document detail", key=f"rag_open_doc_{result.rank}_{result.document_id}"):
                    _open_document_detail(result.document_id)

            header_paths = _extract_header_paths(result.metadata)
            if header_paths:
                st.markdown("**Header paths**")
                for path in header_paths:
                    st.code(path)

            if result.metadata:
                with st.expander("Raw metadata", expanded=False):
                    st.json(result.metadata, expanded=False)

            st.markdown("**Chunk text**")
            st.text(result.text)


def _render_answer_tab(answer_response: AnswerResponse) -> None:
    """Render the grounded answer and citation mapping."""
    st.subheader("Grounded Answer")
    st.markdown(answer_response.answer)

    metrics_col1, metrics_col2, metrics_col3 = st.columns(3)
    metrics_col1.metric("Model", answer_response.trace.model_id)
    metrics_col2.metric("Context Chunks", answer_response.trace.context_chunk_count)
    metrics_col3.metric("Latency", f"{answer_response.trace.duration_ms:.0f} ms")

    used_labels = _citation_labels_in_answer(answer_response.answer)
    if not used_labels:
        st.warning("The answer did not include inline citation labels like [1].")

    st.markdown("**Citation Map**")
    for citation in answer_response.citations:
        used = "Yes" if citation.label in used_labels else "No"
        with st.expander(
            f"{citation.label} · {citation.source_title or 'Unknown source'} · used in answer: {used}",
            expanded=(citation.label in used_labels),
        ):
            st.write(f"**Document ID:** {citation.document_id or '-'}")
            st.write(f"**Chunk Index:** {citation.chunk_index if citation.chunk_index is not None else '-'}")
            if citation.header_path:
                st.write(f"**Header Path:** {citation.header_path}")
            if citation.chunk_uuid:
                st.write(f"**Chunk UUID:** `{citation.chunk_uuid}`")
            st.write("**Excerpt:**")
            st.write(citation.excerpt)


def _render_trace_tab(
    response: SearchResponse,
    answer_response: AnswerResponse | None,
    filtered_doc_ids: list[int],
) -> None:
    """Render search and answer trace details."""
    st.subheader("Search Trace")
    st.json(_search_trace_to_dict(response), expanded=True)

    if filtered_doc_ids:
        st.caption(
            "Document scope is currently applied after retrieval in the UI so it works with "
            "existing embeddings."
        )

    with st.expander("Result Summary Rows", expanded=False):
        st.dataframe(_build_result_rows(response), use_container_width=True, hide_index=True)

    if answer_response is not None:
        st.subheader("Answer Trace")
        st.json(_answer_trace_to_dict(answer_response), expanded=True)
        with st.expander("System Prompt", expanded=False):
            st.code(answer_response.trace.system_prompt, language="markdown")
        with st.expander("User Prompt", expanded=False):
            st.code(answer_response.trace.user_prompt, language="markdown")


def render() -> None:
    """Render the RAG playground page."""
    _inject_styles()
    st.header("RAG Playground")
    st.markdown(
        """
        <div class="rag-banner">
            <p>Run retrieval strategies over the corpus, inspect chunk provenance, and optionally generate a grounded answer with citation labels.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    docs = _load_completed_documents()
    doc_lookup = {doc["id"]: doc for doc in docs}

    with st.form("rag_playground_query_form"):
        query = st.text_area(
            "Query",
            value=st.session_state.get("rag_query_text", ""),
            height=110,
            placeholder="Ask a retrieval question, e.g. How does craving lead to suffering?",
        )
        st.session_state.rag_query_text = query

        config_col1, config_col2, config_col3, config_col4 = st.columns(4)
        with config_col1:
            strategy = st.selectbox(
                "Strategy",
                options=list(RetrievalStrategy),
                index=3,
                format_func=_strategy_label,
            )
        with config_col2:
            k = int(st.slider("Top K", min_value=1, max_value=12, value=5, step=1))
        with config_col3:
            fetch_k = int(st.slider("Fetch K", min_value=5, max_value=40, value=20, step=1))
        with config_col4:
            score_threshold = float(
                st.slider("Score Threshold", min_value=0.0, max_value=1.0, value=0.5, step=0.05)
            )

        filter_col1, filter_col2 = st.columns([2, 1])
        with filter_col1:
            selected_doc_ids = st.multiselect(
                "Document Scope (post-filter)",
                options=[doc["id"] for doc in docs],
                format_func=lambda doc_id: doc_lookup[doc_id]["label"],
                help=(
                    "Applies after retrieval so it works with existing embeddings that do not "
                    "all carry document metadata yet."
                ),
            )
        with filter_col2:
            generate_answer = st.checkbox(
                "Generate grounded answer",
                value=False,
                help="Uses the configured LLM provider via retrieval.llm_client.",
            )

        submitted = st.form_submit_button("Run Query", type="primary")

    if submitted:
        if not query.strip():
            st.warning("Enter a query before running the playground.")
        else:
            try:
                with st.spinner("Running retrieval..."):
                    response = _get_retrieval_engine().search(
                        query=query.strip(),
                        strategy=strategy,
                        k=k,
                        score_threshold=score_threshold,
                        fetch_k=fetch_k,
                    )
                    filtered_response = _apply_post_filter(response, selected_doc_ids)
                    st.session_state[SEARCH_STATE_KEY] = filtered_response

                if generate_answer and filtered_response.results:
                    with st.spinner("Generating grounded answer..."):
                        answer_response = GroundedAnswerService().answer(
                            query=query.strip(),
                            search_results=filtered_response.results,
                        )
                    st.session_state[ANSWER_STATE_KEY] = answer_response
                else:
                    st.session_state[ANSWER_STATE_KEY] = None
            except Exception as exc:
                st.session_state[SEARCH_STATE_KEY] = None
                st.session_state[ANSWER_STATE_KEY] = None
                st.error(f"RAG playground query failed: {exc}")

    response: SearchResponse | None = st.session_state.get(SEARCH_STATE_KEY)
    answer_response: AnswerResponse | None = st.session_state.get(ANSWER_STATE_KEY)

    if response is None:
        st.info(
            "Run a query to inspect retrieved chunks. The page is designed to help us judge "
            "chunking quality, retrieval quality, and grounding quality."
        )
        st.caption(
            "Example queries: What is impermanence? | How does craving lead to suffering? | "
            "How is mindfulness of breathing described?"
        )
        return

    metrics_col1, metrics_col2, metrics_col3, metrics_col4 = st.columns(4)
    metrics_col1.metric("Results", response.total_results)
    metrics_col2.metric("Strategy", _strategy_label(response.strategy))
    duration_ms = response.trace.duration_ms if response.trace is not None else 0.0
    metrics_col3.metric("Search Latency", f"{duration_ms:.0f} ms")
    bm25_size = response.trace.bm25_chunk_count if response.trace is not None else 0
    metrics_col4.metric("BM25 Index Size", bm25_size)

    tab_labels = ["Retrieved Chunks", "Trace"]
    if answer_response is not None:
        tab_labels.insert(0, "Answer")
    tabs = st.tabs(tab_labels)

    tab_index = 0
    if answer_response is not None:
        with tabs[tab_index]:
            _render_answer_tab(answer_response)
        tab_index += 1

    with tabs[tab_index]:
        st.subheader("Retrieved Chunks")
        st.dataframe(_build_result_rows(response), use_container_width=True, hide_index=True)
        if response.results:
            with st.expander("Chunk Inspector View", expanded=False):
                render_chunk_inspector(_to_chunk_like_objects(response.results), key_prefix="rag_results")
            _render_result_cards(response.results)
        else:
            st.info("No results matched the current query and filters.")
    tab_index += 1

    with tabs[tab_index]:
        _render_trace_tab(response, answer_response, selected_doc_ids if submitted else [])
