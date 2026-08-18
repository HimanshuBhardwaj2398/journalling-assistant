"""Pericope tests: planted duplicates must group, adjacency must not."""

import numpy as np
import pandas as pd
import pytest

from atlas.pericopes import align, families, near_duplicate_pairs


def _frame(sutta_uids, chunk_indexes):
    return pd.DataFrame({"sutta_uid": sutta_uids, "chunk_index": chunk_indexes})


def test_planted_duplicates_across_suttas_are_found():
    formula = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    other = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    vectors = np.vstack([formula, other, formula])
    df = _frame(["mn1", "mn1", "dn1"], [0, 1, 0])

    i, j, scores = near_duplicate_pairs(vectors, df, threshold=0.9)

    assert list(zip(i, j)) == [(0, 2)]
    assert scores[0] > 0.99


def test_adjacent_chunks_of_one_sutta_are_not_pericopes():
    formula = np.array([1.0, 0.0], dtype=np.float32)
    vectors = np.vstack([formula, formula])
    df = _frame(["mn1", "mn1"], [0, 1])

    i, j, _ = near_duplicate_pairs(vectors, df, threshold=0.9)

    assert len(i) == 0


def test_distant_chunks_of_one_sutta_still_count():
    """Repetition within a long sutta is real repetition, not a chunker artefact."""
    formula = np.array([1.0, 0.0], dtype=np.float32)
    vectors = np.vstack([formula, formula])
    df = _frame(["dn16", "dn16"], [0, 9])

    i, j, _ = near_duplicate_pairs(vectors, df, threshold=0.9)

    assert list(zip(i, j)) == [(0, 1)]


def test_families_groups_a_repeated_formula_and_reports_mass():
    formula = np.array([1.0, 0.0], dtype=np.float32)
    unique = np.array([0.0, 1.0], dtype=np.float32)
    vectors = np.vstack([formula, formula, formula, unique])
    df = _frame(["mn1", "dn1", "sn1", "mn2"], [0, 0, 0, 0])

    labels, stats = families(vectors, df, threshold=0.9)

    assert stats["n_families"] == 1
    assert stats["duplicate_mass"] == 0.75
    assert len(set(labels[:3])) == 1
    assert labels[3] not in labels[:3]


def test_align_matches_each_chunk_to_its_twin():
    a = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    vectors = np.vstack([a, a[::-1]])
    df = _frame(["mn10", "mn10", "dn22", "dn22"], [0, 1, 0, 1])

    matches = align(vectors, df, "mn10", "dn22")

    assert list(matches["dn22_index"]) == [1, 0]
    assert (matches["cosine"] > 0.99).all()


def test_align_rejects_an_unknown_sutta():
    vectors = np.array([[1.0, 0.0]], dtype=np.float32)
    df = _frame(["mn10"], [0])

    with pytest.raises(ValueError, match="dn22"):
        align(vectors, df, "mn10", "dn22")
