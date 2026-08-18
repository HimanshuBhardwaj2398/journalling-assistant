"""Structure tests: planted blobs must be recovered in the full space."""

import numpy as np

from atlas.structure import centroids, cluster, exemplars


def _blobs(seed=0, per_blob=30):
    rng = np.random.default_rng(seed)
    centres = np.eye(3, 16, dtype=np.float32)
    vectors = np.vstack([c + 0.02 * rng.standard_normal((per_blob, 16)) for c in centres])
    return (vectors / np.linalg.norm(vectors, axis=1, keepdims=True)).astype(np.float32)


def test_cluster_recovers_the_planted_blobs():
    labels = cluster(_blobs(), min_cluster_size=5)

    assert len(set(labels.tolist()) - {-1}) == 3


def test_centroids_are_unit_norm_and_skip_noise():
    vectors = _blobs()
    labels = cluster(vectors, min_cluster_size=5)

    ids, centres = centroids(vectors, labels)

    assert -1 not in ids
    assert len(ids) == len(centres)
    np.testing.assert_allclose(np.linalg.norm(centres, axis=1), 1.0, rtol=1e-5)


def test_exemplar_of_each_cluster_belongs_to_it():
    vectors = _blobs()
    labels = cluster(vectors, min_cluster_size=5)

    for cluster_id, row in exemplars(vectors, labels).items():
        assert labels[row] == cluster_id


def test_centroid_of_a_blob_points_at_its_planted_centre():
    vectors = _blobs()
    labels = cluster(vectors, min_cluster_size=5)

    _, centres = centroids(vectors, labels)
    planted = np.eye(3, 16, dtype=np.float32)

    # Every planted centre should be matched by some recovered centroid.
    assert (np.abs(centres @ planted.T).max(axis=0) > 0.99).all()
