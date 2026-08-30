"""Loader tests: the row -> (vectors, df) transform and the corpus fingerprint."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

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


def _fake_session_scope(rows, recorder):
    """Stand in for db.database.session_scope, recording what the loader executes."""

    class _Result:
        def fetchall(self):
            return rows

        def scalars(self):
            return self

        def all(self):
            return [r[0] for r in rows]

    class _Session:
        def execute(self, query, params):
            recorder.append((str(query), params))
            return _Result()

    @contextmanager
    def scope():
        yield _Session()

    return scope


def test_fetch_reads_through_the_shared_session_scope(monkeypatch):
    """The atlas must not build its own engine — it shares the application pool.

    A private engine skips pool_pre_ping/keepalives (Neon drops idle connections)
    and leaks a fresh pool per call.
    """
    calls = []
    rows = [_row("a", [1.0, 0.0])]
    monkeypatch.setattr(loader, "session_scope", _fake_session_scope(rows, calls))
    monkeypatch.setattr(loader, "VectorSettings", lambda: SimpleNamespace(collection_name="bt"))

    vectors, df = loader.fetch()

    assert len(calls) == 1
    assert calls[0][1] == {"collection": "bt"}
    assert vectors.shape == (1, 2)
    assert list(df["uuid"]) == ["a"]


def test_live_uuids_reads_through_the_shared_session_scope(monkeypatch):
    calls = []
    rows = [("a",), ("b",)]
    monkeypatch.setattr(loader, "session_scope", _fake_session_scope(rows, calls))
    monkeypatch.setattr(loader, "VectorSettings", lambda: SimpleNamespace(collection_name="bt"))

    assert loader.live_uuids() == ["a", "b"]
    assert calls[0][1] == {"collection": "bt"}
