"""Paired bootstrap statistics over per-row eval scores.

Arms are scored over the same rows, so comparisons are paired: we bootstrap
the per-row difference rather than comparing two independent intervals. At
n=23 that is the difference between a usable signal and two overlapping
intervals regardless of the truth.

Pure functions, no I/O — every test runs without a database.
"""

from __future__ import annotations

import random
import statistics
from typing import Any, Mapping


def bootstrap_ci(
    values: list[float],
    *,
    iterations: int = 10000,
    seed: int = 20260830,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for the mean of ``values``.

    Args:
        values: Per-row observations. Must not be empty.
        iterations: Resamples to draw.
        seed: Fixed so a reported interval can be reproduced exactly.
        confidence: Two-sided confidence level.

    Returns:
        (low, high) bounds of the interval.

    Raises:
        ValueError: If ``values`` is empty.
    """
    if not values:
        raise ValueError("bootstrap_ci needs at least one observation")

    rng = random.Random(seed)
    n = len(values)
    means = [statistics.fmean(rng.choices(values, k=n)) for _ in range(iterations)]
    means.sort()
    tail = (1.0 - confidence) / 2.0
    lo_index = max(0, int(tail * iterations) - 1)
    hi_index = min(iterations - 1, int((1.0 - tail) * iterations) - 1)
    return means[lo_index], means[hi_index]


def paired_deltas(
    arm: Mapping[str, float],
    control: Mapping[str, float],
) -> dict[str, Any]:
    """Per-row differences between an arm and its control, over shared rows only.

    Rows missing from either side (a row that errored in one arm) are dropped
    rather than treated as a win — scoring an absent row would manufacture a
    difference that was never measured.

    Args:
        arm: row id -> metric value for the contender.
        control: row id -> metric value for the baseline.

    Returns:
        Dict with n, mean_delta, wins, losses, ties, and the raw deltas list.

    Raises:
        ValueError: If the two arms share no rows.
    """
    shared = sorted(set(arm) & set(control))
    if not shared:
        raise ValueError("arms share no rows; nothing to compare")

    deltas = [arm[row_id] - control[row_id] for row_id in shared]
    return {
        "n": len(shared),
        "mean_delta": statistics.fmean(deltas),
        "wins": sum(1 for d in deltas if d > 0),
        "losses": sum(1 for d in deltas if d < 0),
        "ties": sum(1 for d in deltas if d == 0),
        "deltas": deltas,
    }
