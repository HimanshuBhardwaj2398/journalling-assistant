"""Distribution diagnostics for a unit-norm embedding matrix.

voyage-3.5 returns L2-normalised vectors, so cosine similarity is a plain dot
product and vectors @ vectors.T is the whole similarity matrix.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import skew
from sklearn.decomposition import PCA


def anisotropy(vectors: np.ndarray) -> dict:
    """Mean pairwise cosine, and the length of the mean vector.

    An isotropic cloud on the sphere gives roughly zero for both. High values
    mean the embeddings share a common direction, which compresses the range
    every similarity score can occupy.
    """
    n = len(vectors)
    mean_vector = vectors.mean(axis=0)
    # Sum of all pairwise dots is ||sum of vectors||^2, which saves building the
    # n-by-n matrix; the n self-pairs each contribute 1.0 and come back out.
    total = float(mean_vector @ mean_vector) * n * n - n
    return {
        "mean_pairwise_cosine": total / (n * (n - 1)),
        "mean_vector_norm": float(np.linalg.norm(mean_vector)),
    }


def centre(vectors: np.ndarray) -> np.ndarray:
    """Strip the shared direction and return to the unit sphere.

    Embedding spaces concentrate in a narrow cone, and that common component
    is the same in every vector, so it carries no information while dominating
    every similarity score. Removing it leaves the part that discriminates.
    (Mu & Viswanath 2018, "All-but-the-Top".)
    """
    centred = vectors - vectors.mean(axis=0)
    return np.asarray(centred / np.linalg.norm(centred, axis=1, keepdims=True))


def cosine_distributions(
    vectors: np.ndarray, df: pd.DataFrame, sample: int = 200_000, seed: int = 0
) -> pd.DataFrame:
    """Sampled pair cosines, grouped by how related the two chunks are.

    The gap between within_sutta and cross_nikaya is the space's real
    signal-to-noise: if they overlap, similarity carries little information.
    """
    rng = np.random.default_rng(seed)
    i, j = rng.integers(0, len(vectors), (2, sample))
    keep = i != j
    i, j = i[keep], j[keep]

    sutta = df["sutta_uid"].to_numpy()
    nikaya = df["nikaya"].to_numpy()
    group = np.where(
        sutta[i] == sutta[j],
        "within_sutta",
        np.where(nikaya[i] == nikaya[j], "within_nikaya", "cross_nikaya"),
    )
    return pd.DataFrame({"cosine": np.einsum("ij,ij->i", vectors[i], vectors[j]), "group": group})


def pca_curve(vectors: np.ndarray) -> dict:
    """How many dimensions the corpus actually occupies."""
    cumulative = np.cumsum(PCA().fit(vectors).explained_variance_ratio_)
    return {
        "cumulative": cumulative,
        "dims_50": int(np.searchsorted(cumulative, 0.50) + 1),
        "dims_90": int(np.searchsorted(cumulative, 0.90) + 1),
        "dims_95": int(np.searchsorted(cumulative, 0.95) + 1),
    }


def hubness(vectors: np.ndarray, k: int = 10) -> np.ndarray:
    """How often each chunk lands in another chunk's top-k.

    A long tail here means a few chunks are retrieved for almost any query.
    """
    similarity = vectors @ vectors.T
    np.fill_diagonal(similarity, -np.inf)
    neighbours = np.argpartition(-similarity, k, axis=1)[:, :k]
    return np.bincount(neighbours.ravel(), minlength=len(vectors))


def hub_skew(counts: np.ndarray) -> float:
    """Skewness of the k-occurrence counts. Zero is a healthy, hub-free space."""
    return float(skew(counts))


def length_vs_centrality(vectors: np.ndarray, df: pd.DataFrame) -> float:
    """Correlation between chunk length and average similarity to everything else.

    A strong positive value means long chunks drift toward the centre and get
    retrieved for unrelated queries.
    """
    centrality = (vectors @ vectors.mean(axis=0)).astype(np.float64)
    return float(np.corrcoef(df["word_count"].to_numpy(dtype=np.float64), centrality)[0, 1])
