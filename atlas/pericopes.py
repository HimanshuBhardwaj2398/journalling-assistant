"""Find the Canon's formulaic repeated passages.

The Pali Canon repeats stock formulas verbatim across suttas by design, so a
large near-duplicate mass here is expected rather than a data problem.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components


def near_duplicate_pairs(
    vectors: np.ndarray, df: pd.DataFrame, threshold: float = 0.90
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Chunk pairs above the threshold, excluding neighbours in the same sutta.

    Consecutive chunks of one sutta are similar because the chunker split a
    continuous passage, which is not the repetition we are looking for. Distant
    chunks of the same sutta are kept: long discourses really do repeat.
    """
    similarity = np.triu(vectors @ vectors.T, k=1)
    i, j = np.nonzero(similarity >= threshold)

    sutta = df["sutta_uid"].to_numpy()
    index = df["chunk_index"].to_numpy()
    adjacent = (sutta[i] == sutta[j]) & (np.abs(index[i] - index[j]) <= 1)

    i, j = i[~adjacent], j[~adjacent]
    return i, j, similarity[i, j]


def families(
    vectors: np.ndarray, df: pd.DataFrame, threshold: float = 0.90
) -> tuple[np.ndarray, dict]:
    """Connected components of the near-duplicate graph, plus how much mass they hold."""
    i, j, _ = near_duplicate_pairs(vectors, df, threshold)
    n = len(vectors)
    graph = csr_matrix((np.ones(len(i)), (i, j)), shape=(n, n))

    _, labels = connected_components(graph, directed=False)
    sizes = np.bincount(labels)
    return labels, {
        "n_families": int((sizes > 1).sum()),
        "duplicate_mass": float((sizes[labels] > 1).mean()),
    }


def align(vectors: np.ndarray, df: pd.DataFrame, uid_a: str, uid_b: str) -> pd.DataFrame:
    """Best match in uid_b for every chunk of uid_a.

    MN 10 and DN 22 are near-identical texts, so aligning them is a correctness
    check on the embeddings: a weak result means the space is not trustworthy.
    """
    sutta = df["sutta_uid"].to_numpy()
    a, b = np.flatnonzero(sutta == uid_a), np.flatnonzero(sutta == uid_b)
    for uid, rows in ((uid_a, a), (uid_b, b)):
        if not len(rows):
            raise ValueError(f"No chunks found for sutta {uid}")

    similarity = vectors[a] @ vectors[b].T
    best = similarity.argmax(axis=1)
    index = df["chunk_index"].to_numpy()
    return pd.DataFrame(
        {
            f"{uid_a}_index": index[a],
            f"{uid_b}_index": index[b][best],
            "cosine": similarity[np.arange(len(a)), best],
        }
    )
