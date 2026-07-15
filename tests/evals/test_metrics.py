"""Known-answer tests for IR metrics."""

import math

import pytest

from evals.metrics import hit_rate_at_k, mrr, ndcg_at_k, precision_at_k, recall_at_k

RELEVANT = {"a", "b"}


def test_recall_at_k():
    assert recall_at_k(RELEVANT, ["a", "x", "y"], k=3) == 0.5
    assert recall_at_k(RELEVANT, ["a", "b", "y"], k=3) == 1.0
    assert recall_at_k(RELEVANT, ["a", "b"], k=1) == 0.5  # only top-1 counts


def test_precision_at_k():
    assert precision_at_k(RELEVANT, ["a", "x", "b", "y"], k=4) == 0.5
    assert precision_at_k(RELEVANT, ["x", "y"], k=2) == 0.0


def test_hit_rate_at_k():
    assert hit_rate_at_k(RELEVANT, ["x", "a"], k=2) == 1.0
    assert hit_rate_at_k(RELEVANT, ["x", "a"], k=1) == 0.0


def test_mrr():
    assert mrr(RELEVANT, ["x", "a", "b"]) == 0.5  # first relevant at rank 2
    assert mrr(RELEVANT, ["x", "y"]) == 0.0


def test_ndcg_binary_relevance():
    # relevant at ranks 1 and 3, k=3: DCG = 1/log2(2) + 1/log2(4) = 1 + 0.5
    # IDCG (2 relevant items) = 1/log2(2) + 1/log2(3)
    expected = (1 + 0.5) / (1 + 1 / math.log2(3))
    assert ndcg_at_k(RELEVANT, ["a", "x", "b"], k=3) == pytest.approx(expected)
    assert ndcg_at_k(RELEVANT, ["a", "b"], k=2) == pytest.approx(1.0)


def test_empty_relevant_raises():
    with pytest.raises(ValueError):
        recall_at_k(set(), ["a"], k=1)
