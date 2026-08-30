"""Tests for eval dataset models and JSONL IO."""

import pytest

from evals.dataset import (
    Dimensions,
    EvalRow,
    Persona,
    QuestionType,
    Register,
    load_dataset,
    save_dataset,
)


def _row(**overrides) -> EvalRow:
    base = dict(
        id="syn_001",
        question="How does one develop mindfulness of breathing?",
        reference_answer="By sitting down, establishing mindfulness...",
        sutta_uids=["mn118"],
        chunk_uuids=["uuid-abc"],
        source_document_ids=[42],
        dimensions=Dimensions(
            question_type=QuestionType.PRACTICAL,
            persona=Persona.NEW_MEDITATOR,
            register=Register.COLLOQUIAL,
        ),
        origin="synthetic",
        model_version="groq/openai/gpt-oss-120b",
    )
    base.update(overrides)
    return EvalRow(**base)


def test_valid_row_roundtrips():
    row = _row()
    assert row.dimensions.register == Register.COLLOQUIAL


def test_blank_question_rejected():
    with pytest.raises(ValueError):
        _row(question="   ")


def test_row_requires_at_least_one_ground_truth_anchor():
    with pytest.raises(ValueError):
        _row(sutta_uids=[], chunk_uuids=[], source_document_ids=[])


def test_manual_row_needs_no_chunk_uuids():
    row = _row(origin="manual", chunk_uuids=[], source_document_ids=[], model_version=None)
    assert row.sutta_uids == ["mn118"]


def test_jsonl_roundtrip(tmp_path):
    rows = [_row(), _row(id="syn_002", question="What are the five hindrances?")]
    path = tmp_path / "ds.jsonl"
    save_dataset(rows, path)
    loaded = load_dataset(path)
    assert [r.id for r in loaded] == ["syn_001", "syn_002"]
    assert loaded[0].dimensions.question_type == QuestionType.PRACTICAL


def test_load_rejects_duplicate_ids(tmp_path):
    rows = [_row(), _row()]
    path = tmp_path / "ds.jsonl"
    save_dataset(rows, path)
    with pytest.raises(ValueError, match="duplicate"):
        load_dataset(path)
