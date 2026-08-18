"""The map: UMAP for looking at, HDBSCAN for grouping."""

from __future__ import annotations

import numpy as np
from sklearn.cluster import HDBSCAN


def project(vectors: np.ndarray, n_neighbors: int = 15, seed: int = 42) -> np.ndarray:
    """A 2D layout for viewing only.

    Never cluster this output: UMAP distorts density by construction, so groups
    that look obvious here can be artefacts of the projection.
    """
    import umap  # imported lazily; numba compilation makes this slow to import

    return umap.UMAP(
        n_neighbors=n_neighbors, min_dist=0.1, metric="cosine", random_state=seed
    ).fit_transform(vectors)


def cluster(vectors: np.ndarray, min_cluster_size: int = 15) -> np.ndarray:
    """HDBSCAN over the full embedding, labelling outliers -1.

    euclidean is exact here rather than an approximation: on unit-norm vectors
    ||a-b||^2 == 2 - 2*cos(a,b), so the two orderings are identical.

    copy=True is explicit because vectors is the shared cached matrix every other
    module reads, and the sklearn default is due to flip in 1.10.
    """
    return HDBSCAN(min_cluster_size=min_cluster_size, metric="euclidean", copy=True).fit_predict(
        vectors
    )


def centroids(vectors: np.ndarray, labels: np.ndarray) -> tuple[list[int], np.ndarray]:
    """The centre point of each cluster, back on the unit sphere."""
    ids = sorted(set(labels.tolist()) - {-1})
    centres = np.array([vectors[labels == cluster_id].mean(axis=0) for cluster_id in ids])
    return ids, centres / np.linalg.norm(centres, axis=1, keepdims=True)


def exemplars(vectors: np.ndarray, labels: np.ndarray) -> dict[int, int]:
    """Row index of the chunk nearest each centroid — the region's representative."""
    ids, centres = centroids(vectors, labels)
    chosen = {}
    for cluster_id, centre in zip(ids, centres):
        members = np.flatnonzero(labels == cluster_id)
        chosen[cluster_id] = int(members[np.argmax(vectors[members] @ centre)])
    return chosen
