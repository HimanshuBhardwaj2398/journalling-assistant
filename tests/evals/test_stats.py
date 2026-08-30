"""Paired bootstrap statistics over per-row eval scores."""

import pytest

from evals.stats import bootstrap_ci, paired_deltas


def test_bootstrap_ci_of_constant_values_is_that_constant():
    lo, hi = bootstrap_ci([0.5] * 20, iterations=200, seed=1)
    assert lo == pytest.approx(0.5)
    assert hi == pytest.approx(0.5)


def test_bootstrap_ci_brackets_the_mean():
    values = [0.0, 0.25, 0.5, 0.75, 1.0] * 4
    lo, hi = bootstrap_ci(values, iterations=2000, seed=7)
    assert lo < 0.5 < hi


def test_bootstrap_ci_is_seed_reproducible():
    values = [0.1, 0.9, 0.3, 0.7, 0.5]
    assert bootstrap_ci(values, iterations=500, seed=42) == bootstrap_ci(
        values, iterations=500, seed=42
    )


def test_bootstrap_ci_actually_depends_on_the_seed():
    # Reproducibility alone is satisfied by ignoring the seed entirely. Only a
    # continuous input has a fine enough grid of resample means for different
    # seeds to land on different percentiles, so this is where the wiring is
    # provable. Reported intervals rest on the seed being real.
    values = [i / 40 for i in range(40)]
    assert bootstrap_ci(values, seed=42) != bootstrap_ci(values, seed=43)


def test_bootstrap_ci_rejects_empty_input():
    with pytest.raises(ValueError):
        bootstrap_ci([], iterations=10, seed=1)


def test_paired_deltas_counts_wins_losses_ties():
    result = paired_deltas(
        {"r1": 1.0, "r2": 0.5, "r3": 0.25},
        {"r1": 0.5, "r2": 0.5, "r3": 1.0},
    )
    assert result["wins"] == 1  # r1: 1.0 > 0.5
    assert result["ties"] == 1  # r2: equal
    assert result["losses"] == 1  # r3: 0.25 < 1.0
    assert result["mean_delta"] == pytest.approx((0.5 + 0.0 - 0.75) / 3)


def test_paired_deltas_uses_only_shared_rows():
    # A row missing from one arm (it errored) must not be scored as a win.
    result = paired_deltas({"r1": 1.0, "r2": 1.0}, {"r1": 0.0})
    assert result["n"] == 1
    assert result["wins"] == 1


def test_paired_deltas_rejects_disjoint_arms():
    with pytest.raises(ValueError):
        paired_deltas({"r1": 1.0}, {"r2": 1.0})
