from types import SimpleNamespace

import numpy as np

from api.lib.compute.colmap_geometric_data import (
    _reject_outlier_poses,
    colmap_compute_geometric_data,
)


def test_reject_outlier_poses_drops_far_registration() -> None:
    cluster = np.random.default_rng(0).normal(scale=0.5, size=(50, 3))
    positions = np.vstack([cluster, [[300.0, -200.0, 100.0]]])
    up_vectors = np.tile(np.array([0.0, 1.0, 0.0]), (51, 1))

    kept_positions, kept_up_vectors = _reject_outlier_poses(positions, up_vectors)

    assert len(kept_positions) == 50
    assert len(kept_up_vectors) == 50
    np.testing.assert_allclose(kept_positions, cluster)


def test_reject_outlier_poses_keeps_continuous_camera_path() -> None:
    # A path spreading continuously up to 35 units has no isolated outlier.
    positions = np.linspace(0.0, 35.0, 40).reshape(-1, 1) * np.array([1.0, 0.0, 0.0])
    up_vectors = np.tile(np.array([0.0, 1.0, 0.0]), (40, 1))

    kept_positions, _ = _reject_outlier_poses(positions, up_vectors)

    assert len(kept_positions) == 40


def test_reject_outlier_poses_keeps_short_input_unchanged() -> None:
    positions = np.array([[1.0, 2.0, 3.0]])
    up_vectors = np.array([[0.0, 1.0, 0.0]])

    kept_positions, kept_up_vectors = _reject_outlier_poses(positions, up_vectors)

    np.testing.assert_allclose(kept_positions, positions)
    np.testing.assert_allclose(kept_up_vectors, up_vectors)


def test_colmap_compute_geometric_data_ignores_outlier_pose(
    tmp_path, monkeypatch
) -> None:
    import pycolmap

    def fake_image(translation: np.ndarray) -> SimpleNamespace:
        pose = SimpleNamespace(
            translation=translation,
            rotation=SimpleNamespace(matrix=lambda: np.eye(3)),
        )
        return SimpleNamespace(cam_from_world=lambda: pose)

    translations = [np.array([1.0, 0.0, -3.0 + 0.1 * i]) for i in range(50)]
    translations.append(np.array([300.0, -200.0, 100.0]))
    fake_reconstruction = SimpleNamespace(
        images={i: fake_image(t) for i, t in enumerate(translations)}
    )
    monkeypatch.setattr(
        pycolmap, "Reconstruction", lambda sparse_dir: fake_reconstruction
    )

    geometric_data = colmap_compute_geometric_data(str(tmp_path))

    assert geometric_data.radius < 10.0
    assert len(geometric_data.positions) == 50
