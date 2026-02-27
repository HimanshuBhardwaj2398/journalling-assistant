"""
Unit tests for scripts/validate_chunk_toc_integrity.py helpers.

Run:
    poetry run pytest tests/test_chunk_toc_validation.py
"""

import importlib.util
import sys
from pathlib import Path


def _load_validation_module():
    """Load the validation script as a module for unit testing."""
    repo_root = Path(__file__).resolve().parent.parent
    module_path = repo_root / "scripts" / "validate_chunk_toc_integrity.py"
    spec = importlib.util.spec_from_file_location("validate_chunk_toc_integrity", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validation = _load_validation_module()


def _status_for(checks, name):
    """Extract status for a named check from CheckResult list."""
    for check in checks:
        if check.name == name:
            return check.status
    raise AssertionError(f"Check '{name}' not found")


def test_sample_documents_is_deterministic_with_seed():
    docs = [{"id": idx} for idx in range(1, 11)]

    sample_a = validation.sample_documents(docs, sample_size=5, seed=42)
    sample_b = validation.sample_documents(docs, sample_size=5, seed=42)
    sample_c = validation.sample_documents(docs, sample_size=5, seed=99)

    ids_a = [doc["id"] for doc in sample_a]
    ids_b = [doc["id"] for doc in sample_b]
    ids_c = [doc["id"] for doc in sample_c]

    assert ids_a == ids_b
    assert ids_a != ids_c


def test_validate_chunk_index_integrity_contiguous_and_duplicate_detection():
    valid_chunks = [
        {"chunk_index": 0},
        {"chunk_index": 1},
        {"chunk_index": 2},
    ]
    valid_checks = validation.validate_chunk_index_integrity(valid_chunks)
    assert _status_for(valid_checks, "chunk_indices_unique") == validation.PASS
    assert _status_for(valid_checks, "chunk_indices_contiguous") == validation.PASS
    assert _status_for(valid_checks, "chunk_indices_ordered") == validation.PASS

    invalid_chunks = [
        {"chunk_index": 0},
        {"chunk_index": 2},
        {"chunk_index": 2},
    ]
    invalid_checks = validation.validate_chunk_index_integrity(invalid_chunks)
    assert _status_for(invalid_checks, "chunk_indices_unique") == validation.FAIL
    assert _status_for(invalid_checks, "chunk_indices_contiguous") == validation.FAIL
    assert _status_for(invalid_checks, "chunk_indices_ordered") == validation.FAIL


def test_validate_toc_entries_flags_missing_markdown_headers():
    markdown = "# Root\n## A\n## B\n"
    markdown_headers = validation.extract_markdown_headers(markdown)
    markdown_paths = [entry["path_from_root"] for entry in markdown_headers]

    toc = {
        "entries": [
            {"id": "h1_0", "level": 1, "text": "Root", "parent_id": None},
            {"id": "h2_1", "level": 2, "text": "A", "parent_id": "h1_0"},
        ],
        "text": "Root\n  A",
    }

    result = validation.validate_toc_entries(toc, markdown_paths)
    assert "Root > B" in result["missing_paths"]
    assert _status_for(result["checks"], "toc_covers_markdown_headers") == validation.FAIL


def test_validate_toc_entries_detects_orphan_and_cycle():
    orphan_toc = {
        "entries": [
            {"id": "h1_0", "level": 1, "text": "Root", "parent_id": "missing_parent"},
        ]
    }
    orphan_result = validation.validate_toc_entries(orphan_toc, [])
    assert _status_for(orphan_result["checks"], "toc_parent_references") == validation.FAIL

    cycle_toc = {
        "entries": [
            {"id": "a", "level": 1, "text": "A", "parent_id": "b"},
            {"id": "b", "level": 2, "text": "B", "parent_id": "a"},
        ]
    }
    cycle_result = validation.validate_toc_entries(cycle_toc, [])
    assert _status_for(cycle_result["checks"], "toc_cycles") == validation.FAIL


def test_validate_chunk_metadata_schema_and_path_validation():
    chunks = [
        {
            "chunk_index": 0,
            "chunk_metadata": {
                "all_header_paths": ["Root > Child"],
                "header_level_map": {"Root": 1},
            },
        },
        {
            "chunk_index": 1,
            "chunk_metadata": {
                "all_header_paths": ["OtherRoot > Section"],
                "header_level_map": {"OtherRoot": 1, "Section": 2},
            },
        },
    ]
    markdown_paths = ["Root > Child"]

    result = validation.validate_chunk_metadata(chunks, markdown_paths)

    assert _status_for(result["checks"], "chunk_metadata_schema") == validation.FAIL
    assert _status_for(result["checks"], "chunk_paths_match_markdown") == validation.WARN


def test_classify_similarity_thresholds():
    assert validation.classify_similarity(0.995) == validation.PASS
    assert validation.classify_similarity(0.990) == validation.WARN
    assert validation.classify_similarity(0.979) == validation.FAIL

    reconstruction = validation.evaluate_reconstruction(
        markdown="same text",
        chunks=[{"chunk_text": "same text"}],
    )
    assert reconstruction["status"] == validation.PASS
