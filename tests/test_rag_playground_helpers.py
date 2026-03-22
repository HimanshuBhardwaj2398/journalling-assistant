"""Tests for RAG playground helper behavior."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ["DEBUG"] = "false"

from retrieval.query import RetrievalStrategy, SearchResponse, SearchResult
from retrieval.utils import extract_header_paths as _extract_header_paths
from views.rag_playground import (
    _answer_trace_to_dict,
    _apply_post_filter,
    _build_result_rows,
    _citation_labels_in_answer,
    _format_score,
    _search_trace_to_dict,
)


def test_format_score_handles_missing_values(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    assert _format_score(None) == "n/a"
    assert _format_score(0.123456) == "0.1235"


def test_extract_header_paths_supports_legacy_and_new_metadata(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    assert _extract_header_paths({"all_header_paths": ["DN > Sutta 1"]}) == ["DN > Sutta 1"]
    assert _extract_header_paths({"Header 1": "DN", "Header 2": "Sutta 1"}) == ["DN > Sutta 1"]


def test_build_result_rows_includes_header_preview(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    response = SearchResponse(
        query="What is mindfulness?",
        strategy=RetrievalStrategy.HYBRID,
        results=[
            SearchResult(
                text="Mindfulness is established with care.",
                score=0.5,
                chunk_uuid="uuid-1",
                document_id=12,
                source_title="Middle Discourses",
                chunk_index=2,
                metadata={"all_header_paths": ["MN > Mindfulness"]},
                rank=1,
            )
        ],
    )

    rows = _build_result_rows(response)

    assert rows[0]["Rank"] == 1
    assert rows[0]["Header Path"] == "MN > Mindfulness"
    assert rows[0]["Score"] == "0.5000"


def test_citation_label_extraction_detects_multiple_references(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    labels = _citation_labels_in_answer("This is supported by [1] and also [3].")
    assert labels == {"[1]", "[3]"}


def test_apply_post_filter_reduces_results(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    response = SearchResponse(
        query="What is suffering?",
        strategy=RetrievalStrategy.SIMILARITY,
        results=[
            SearchResult(text="a", document_id=1, rank=1),
            SearchResult(text="b", document_id=2, rank=2),
        ],
    )

    filtered = _apply_post_filter(response, [2])

    assert filtered.total_results == 1
    assert filtered.results[0].document_id == 2


def test_search_trace_dict_includes_langfuse_fields(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    response = SearchResponse(
        query="What is suffering?",
        strategy=RetrievalStrategy.SIMILARITY,
        results=[],
    )
    response.trace = type(
        "Trace",
        (),
        {
            "collection_name": "documents",
            "embedding_model": "voyage-3.5",
            "requested_k": 5,
            "fetch_k": 20,
            "score_threshold": 0.5,
            "started_at": "2026-03-22T00:00:00+00:00",
            "duration_ms": 12.3,
            "bm25_chunk_count": 100,
            "langfuse_trace_id": "trace-search-1",
            "langfuse_trace_url": "https://langfuse.local/trace/trace-search-1",
            "notes": ["note"],
        },
    )()

    payload = _search_trace_to_dict(response)

    assert payload["langfuse_trace_id"] == "trace-search-1"
    assert payload["langfuse_trace_url"] == "https://langfuse.local/trace/trace-search-1"


def test_answer_trace_dict_includes_langfuse_fields(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    answer_response = type(
        "AnswerResponse",
        (),
        {
            "trace": type(
                "AnswerTrace",
                (),
                {
                    "model_id": "openai/gpt-4o-mini",
                    "context_chunk_count": 3,
                    "context_char_count": 2500,
                    "duration_ms": 50.0,
                    "langfuse_trace_id": "trace-answer-1",
                    "langfuse_trace_url": "https://langfuse.local/trace/trace-answer-1",
                },
            )()
        },
    )()

    payload = _answer_trace_to_dict(answer_response)

    assert payload["langfuse_trace_id"] == "trace-answer-1"
    assert payload["langfuse_trace_url"] == "https://langfuse.local/trace/trace-answer-1"
