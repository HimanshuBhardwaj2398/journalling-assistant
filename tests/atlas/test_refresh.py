"""Refresh CLI: reports drift honestly and rebuilds only when asked."""

import numpy as np
import pandas as pd
import pytest

from atlas import loader, refresh


@pytest.fixture
def fake_corpus(monkeypatch):
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
    monkeypatch.setattr(loader, "fetch", lambda: (matrix, meta))
    return matrix, meta


def test_reports_no_cache_as_stale(tmp_path):
    status = refresh.status(cache_dir=tmp_path, uuids=["a", "b"])

    assert status["cached"] is None
    assert status["stale"] is True


def test_matching_fingerprint_is_fresh(fake_corpus, tmp_path):
    loader.load(cache_dir=tmp_path)

    status = refresh.status(cache_dir=tmp_path, uuids=["a", "b"])

    assert status["stale"] is False
    assert status["cached_chunks"] == 2
    assert status["live_chunks"] == 2


def test_new_ingestion_shows_up_as_drift(fake_corpus, tmp_path):
    loader.load(cache_dir=tmp_path)

    status = refresh.status(cache_dir=tmp_path, uuids=["a", "b", "c"])

    assert status["stale"] is True
    assert status["cached_chunks"] == 2
    assert status["live_chunks"] == 3


def test_rebuild_makes_the_cache_fresh_again(fake_corpus, tmp_path):
    loader.load(cache_dir=tmp_path)
    (tmp_path / "vectors.npy").unlink()

    refresh.rebuild(cache_dir=tmp_path)

    assert (tmp_path / "vectors.npy").exists()
    assert refresh.status(cache_dir=tmp_path, uuids=["a", "b"])["stale"] is False
