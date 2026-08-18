"""Geometry tests, all against synthetic vectors with a known answer."""

import numpy as np
import pandas as pd

from atlas.geometry import anisotropy, centre, cosine_distributions, hubness, pca_curve


def _unit(vectors):
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def test_orthonormal_vectors_are_isotropic():
    vectors = np.eye(50, dtype=np.float32)

    result = anisotropy(vectors)

    assert abs(result["mean_pairwise_cosine"]) < 1e-6
    assert result["mean_vector_norm"] < 0.2


def test_a_cone_matches_the_closed_form_anisotropy():
    """A cone around one axis with gaussian noise has mean cosine 1/(1 + sigma^2 * d)."""
    rng = np.random.default_rng(0)
    sigma, dims, n = 0.05, 64, 200
    direction = np.zeros((n, dims), dtype=np.float32)
    direction[:, 0] = 1.0
    vectors = _unit(direction + sigma * rng.standard_normal((n, dims)).astype(np.float32))

    result = anisotropy(vectors)

    assert abs(result["mean_pairwise_cosine"] - 1 / (1 + sigma**2 * dims)) < 0.02
    # The two measures are algebraically linked: mean_pairwise == (n*||mean||^2 - 1)/(n - 1).
    linked = (n * result["mean_vector_norm"] ** 2 - 1) / (n - 1)
    assert abs(result["mean_pairwise_cosine"] - linked) < 1e-6


def test_isotropic_noise_is_not_mistaken_for_a_cone():
    rng = np.random.default_rng(0)
    vectors = _unit(rng.standard_normal((300, 64)).astype(np.float32))

    assert abs(anisotropy(vectors)["mean_pairwise_cosine"]) < 0.05


def test_cosine_distributions_separate_within_sutta_from_cross_nikaya():
    rng = np.random.default_rng(0)
    a = _unit(np.tile([1.0, 0.0], (20, 1)) + 0.01 * rng.standard_normal((20, 2)))
    b = _unit(np.tile([0.0, 1.0], (20, 1)) + 0.01 * rng.standard_normal((20, 2)))
    vectors = np.vstack([a, b]).astype(np.float32)
    df = pd.DataFrame(
        {
            "sutta_uid": ["mn1"] * 20 + ["dn1"] * 20,
            "nikaya": ["mn"] * 20 + ["dn"] * 20,
        }
    )

    out = cosine_distributions(vectors, df, sample=5000, seed=0)
    means = out.groupby("group")["cosine"].mean()

    assert means["within_sutta"] > 0.99
    assert means["cross_nikaya"] < 0.1


def test_pca_curve_finds_the_true_rank():
    rng = np.random.default_rng(0)
    basis = _unit(rng.standard_normal((3, 40)))
    vectors = _unit(rng.standard_normal((100, 3)) @ basis).astype(np.float32)

    curve = pca_curve(vectors)

    assert curve["dims_95"] <= 3


def test_hubness_finds_a_point_sitting_on_the_cloud_axis():
    """The real hub mechanism: a point near the centroid of an anisotropic cloud."""
    rng = np.random.default_rng(0)
    direction = np.zeros((60, 8), dtype=np.float32)
    direction[:, 0] = 1.0
    vectors = _unit(direction + 0.6 * rng.standard_normal((60, 8)).astype(np.float32))
    vectors[0] = np.eye(8, dtype=np.float32)[0]

    counts = hubness(vectors, k=5)

    assert counts[0] >= 2 * counts.mean()
    assert (counts > counts[0]).sum() < 3


def test_centring_removes_the_common_direction():
    rng = np.random.default_rng(0)
    direction = np.zeros((200, 32), dtype=np.float32)
    direction[:, 0] = 1.0
    vectors = _unit(direction + 0.3 * rng.standard_normal((200, 32)).astype(np.float32))

    centred = centre(vectors)

    # sigma=0.3 at d=32 gives 1/(1 + 0.09*32) ~= 0.26, plainly anisotropic.
    assert anisotropy(vectors)["mean_pairwise_cosine"] > 0.2
    assert abs(anisotropy(centred)["mean_pairwise_cosine"]) < 0.05
    np.testing.assert_allclose(np.linalg.norm(centred, axis=1), 1.0, rtol=1e-5)


def test_centring_preserves_relative_structure():
    """Two tight groups must stay separable after the common component goes."""
    rng = np.random.default_rng(0)
    base = np.zeros((100, 16), dtype=np.float32)
    base[:, 0] = 1.0
    base[50:, 1] = 0.4
    vectors = _unit(base + 0.05 * rng.standard_normal((100, 16)).astype(np.float32))

    centred = centre(vectors)
    first_centre = centred[:50].mean(axis=0)
    second_centre = centred[50:].mean(axis=0)

    within = float((centred[:50] @ first_centre).mean())
    across = float((centred[:50] @ second_centre).mean())

    assert within > across
