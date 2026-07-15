"""IR metrics over ranked retrieval results. Pure functions, binary relevance.

`relevant` is the ground-truth id set; `retrieved` is the ranked id list
(rank 1 first). Ids are opaque strings — the runner decides the id space
(chunk UUID or document id) per dataset row.
"""

from __future__ import annotations

import math
from typing import Sequence


def _check(relevant: set[str]) -> None:
    if not relevant:
        raise ValueError("relevant set must not be empty")


def recall_at_k(relevant: set[str], retrieved: Sequence[str], k: int) -> float:
    _check(relevant)
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def precision_at_k(relevant: set[str], retrieved: Sequence[str], k: int) -> float:
    _check(relevant)
    if k <= 0:
        raise ValueError("k must be positive")
    return len(set(retrieved[:k]) & relevant) / k


def hit_rate_at_k(relevant: set[str], retrieved: Sequence[str], k: int) -> float:
    _check(relevant)
    return 1.0 if set(retrieved[:k]) & relevant else 0.0


def mrr(relevant: set[str], retrieved: Sequence[str]) -> float:
    _check(relevant)
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(relevant: set[str], retrieved: Sequence[str], k: int) -> float:
    _check(relevant)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(retrieved[:k], start=1)
        if item in relevant
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0
