"""Loader tests: the row -> (vectors, df) transform and the corpus fingerprint."""

import json

import numpy as np
import pytest

from atlas.loader import fingerprint, rows_to_frame
from core.exceptions import CollectionError


def _row(uuid, vec, **kw):
    fields = {
        "uuid": uuid,
        "chunk_text": "some text",
        "embedding": json.dumps(vec),
        "sutta_uid": "mn1",
        "nikaya": "mn",
        "doc_title": "The Root of All Things",
        "word_count": 200,
        "chunk_index": 0,
    }
    fields.update(kw)
    return tuple(fields.values())


def test_rows_to_frame_parses_pgvector_json_text():
    rows = [_row("a", [1.0, 0.0]), _row("b", [0.0, 1.0])]

    vectors, df = rows_to_frame(rows)

    assert vectors.shape == (2, 2)
    assert vectors.dtype == np.float32
    np.testing.assert_allclose(vectors[0], [1.0, 0.0])
    assert list(df["uuid"]) == ["a", "b"]
    assert "embedding" not in df.columns


def test_rows_to_frame_rejects_an_empty_collection():
    with pytest.raises(CollectionError, match="meditation_chunks"):
        rows_to_frame([])


def test_fingerprint_ignores_row_order():
    assert fingerprint(["b", "a"]) == fingerprint(["a", "b"])


def test_fingerprint_changes_when_the_corpus_changes():
    assert fingerprint(["a", "b"]) != fingerprint(["a", "b", "c"])
