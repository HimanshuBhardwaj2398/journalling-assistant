"""Loader tests: the row -> (vectors, df) transform and the corpus fingerprint."""

import json

import numpy as np
import pandas as pd
import pytest

from atlas import loader
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


def test_load_writes_the_cache_then_serves_it_without_refetching(tmp_path, monkeypatch):
    """Regression: the cache round-trip is what a rename collision silently broke."""
    calls = []
    matrix = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    meta = pd.DataFrame(
        {
            "uuid": ["a", "b"],
            "chunk_text": ["one", "two"],
            "sutta_uid": ["mn1", "dn1"],
            "nikaya": ["mn", "dn"],
            "doc_title": ["t", "t"],
            "word_count": [3, 4],
            "chunk_index": [0, 0],
        }
    )

    def fake_fetch():
        calls.append(1)
        return matrix, meta

    monkeypatch.setattr(loader, "fetch", fake_fetch)

    first_vectors, first_meta = loader.load(cache_dir=tmp_path)
    second_vectors, second_meta = loader.load(cache_dir=tmp_path)

    assert len(calls) == 1
    np.testing.assert_array_equal(first_vectors, matrix)
    np.testing.assert_array_equal(second_vectors, matrix)
    assert list(second_meta["uuid"]) == ["a", "b"]
    assert (tmp_path / "vectors.npy").exists()
    assert json.loads((tmp_path / "fingerprint.json").read_text())["corpus"] == fingerprint(
        ["a", "b"]
    )


def test_refresh_bypasses_the_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        loader,
        "fetch",
        lambda: (
            calls.append(1),
            (np.zeros((1, 2), dtype=np.float32), pd.DataFrame({"uuid": ["a"]})),
        )[1],
    )

    loader.load(cache_dir=tmp_path)
    loader.load(refresh=True, cache_dir=tmp_path)

    assert len(calls) == 2
