"""Tests for document detail/browse helper compatibility behavior."""

from types import SimpleNamespace

from views.components.chunk_inspector import (
    _clamp_index,
    _legacy_header_path_from_metadata,
)
from views.document_detail import (
    _build_toc_from_chunks,
    _chunk_matches_header,
    _extract_paths_from_chunk_metadata,
    _flatten_toc,
    _get_effective_toc,
)


def _chunk(index: int, metadata: dict, text: str = "chunk text"):
    """Create a lightweight chunk-like object for helper tests."""
    return SimpleNamespace(
        chunk_index=index,
        chunk_metadata=metadata,
        chunk_text=text,
    )


def test_extract_paths_supports_new_metadata_shape():
    paths = _extract_paths_from_chunk_metadata(
        {
            "all_header_paths": ["DN > Sutta 1", "DN > Sutta 2"],
            "header_level_map": {"DN": 1, "Sutta 1": 2, "Sutta 2": 2},
        }
    )
    assert paths == ["DN > Sutta 1", "DN > Sutta 2"]


def test_extract_paths_supports_legacy_metadata_shape():
    paths = _extract_paths_from_chunk_metadata(
        {
            "Header 1": "DN",
            "Header 2": "Sutta 1",
        }
    )
    assert paths == ["DN > Sutta 1"]


def test_extract_paths_supports_legacy_all_headers_shape():
    paths = _extract_paths_from_chunk_metadata(
        {
            "all_headers": [
                {"Header 1": "DN", "Header 2": "Sutta 1"},
                {"Header 1": "DN", "Header 2": "Sutta 2"},
            ]
        }
    )
    assert paths == ["DN > Sutta 1", "DN > Sutta 2"]


def test_build_toc_from_chunks_uses_legacy_paths():
    chunks = [
        _chunk(0, {"Header 1": "DN", "Header 2": "Sutta 1"}),
        _chunk(1, {"Header 1": "DN", "Header 2": "Sutta 2"}),
    ]
    toc = _build_toc_from_chunks(chunks)
    flattened = _flatten_toc(toc)

    assert "DN" in flattened
    assert "DN > Sutta 1" in flattened
    assert "DN > Sutta 2" in flattened


def test_get_effective_toc_prefers_document_toc():
    doc_toc = {
        "entries": [
            {
                "id": "h1_0",
                "level": 1,
                "text": "DN",
                "parent_id": None,
                "path_from_root": "DN",
            }
        ],
        "text": "DN",
    }
    doc = SimpleNamespace(doc_metadata={"table_of_contents": doc_toc})
    chunks = [_chunk(0, {"Header 1": "Fallback"})]

    toc, source = _get_effective_toc(doc, chunks)
    assert source == "document"
    assert _flatten_toc(toc) == ["DN"]


def test_get_effective_toc_falls_back_to_chunks():
    doc = SimpleNamespace(doc_metadata={})
    chunks = [_chunk(0, {"Header 1": "DN", "Header 2": "Sutta 1"})]

    toc, source = _get_effective_toc(doc, chunks)
    flattened = _flatten_toc(toc)

    assert source == "chunks"
    assert flattened == ["DN", "DN > Sutta 1"]


def test_chunk_matches_header_for_legacy_chunk():
    chunk = _chunk(0, {"Header 1": "DN", "Header 2": "Sutta 1"})
    assert _chunk_matches_header(chunk, "DN")
    assert _chunk_matches_header(chunk, "DN > Sutta 1")
    assert not _chunk_matches_header(chunk, "AN")


def test_clamp_index_keeps_number_input_in_bounds():
    assert _clamp_index(-4, 10) == 0
    assert _clamp_index(3, 10) == 3
    assert _clamp_index(99, 10) == 9
    assert _clamp_index(0, 0) == 0


def test_legacy_header_path_builder():
    path = _legacy_header_path_from_metadata(
        {
            "Header 1": "DN",
            "Header 2": "Sutta 1",
            "other": "value",
        }
    )
    assert path == "DN > Sutta 1"
