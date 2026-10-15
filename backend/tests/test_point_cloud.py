import json
from pathlib import Path

import numpy as np
import pytest
from plyfile import PlyData, PlyElement

from api.config import config
from api.lib.compute.colmap_geometric_data import ColmapGeometricData
from api.lib.compute.point_cloud import (
    POINT_CLOUD_BINARY_FILENAME,
    POINT_CLOUD_META_FILENAME,
    compute_plan_point_cloud,
    generate_plan_point_cloud,
)


def _make_splat_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    means = np.array(
        [
            [1.0, 2.0, 2.0],
            [0.0, 0.0, 0.0],
            [-4.0, 0.5, 2.0],
            [9.0, 9.0, 9.0],
        ]
    )
    scales = np.array(
        [
            [-1.0, -1.0, -1.0],
            [0.0, 0.0, 0.0],
            [-2.0, -2.0, -2.0],
            [0.0, 0.0, 0.0],
        ]
    )
    opacities = np.array([20.0, 20.0, -2.0, -2.0])
    return means, scales, opacities


def test_compute_plan_point_cloud_filters_by_decoded_density() -> None:
    means, scales, opacities = _make_splat_arrays()

    positions, cm_per_unit = compute_plan_point_cloud(
        means,
        scales,
        opacities,
        center=np.zeros(3),
        world_rotation=np.eye(3),
        radius=2.0,
        threshold=1.0,
    )

    # radius**3 = 8: densities are ~20.1, ~1.0, ~48.1, ~0.12
    np.testing.assert_allclose(positions, [[1.0, 2.0, 2.0], [-4.0, 0.5, 2.0]])
    assert positions.dtype == np.float32
    assert cm_per_unit is None


def test_compute_plan_point_cloud_applies_transposed_rotation() -> None:
    means = np.array([[2.0, 2.0, 3.0], [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
    scales = np.zeros((3, 3))
    opacities = np.full(3, 20.0)
    world_rotation = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])

    positions, _ = compute_plan_point_cloud(
        means,
        scales,
        opacities,
        center=np.array([1.0, 2.0, 3.0]),
        world_rotation=world_rotation,
        radius=1.0,
        threshold=0.0,
    )

    np.testing.assert_allclose(
        positions, [[0.0, -1.0, 0.0], [-2.0, 1.0, -3.0], [-1.0, 0.0, -2.0]]
    )


def test_compute_plan_point_cloud_cm_per_unit_from_camera_height() -> None:
    means = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    scales = np.zeros((3, 3))
    opacities = np.full(3, 20.0)
    camera_positions = np.array([[0.0, 0.0, 5.0], [1.0, 0.0, 5.0]])

    _, cm_per_unit = compute_plan_point_cloud(
        means,
        scales,
        opacities,
        center=np.zeros(3),
        world_rotation=np.eye(3),
        radius=1.0,
        threshold=0.0,
        camera_positions=camera_positions,
    )

    assert cm_per_unit == pytest.approx(170.0 * 0.9 / 5.0)


def test_compute_plan_point_cloud_cm_per_unit_is_none_when_degenerate() -> None:
    means = np.array([[0.0, 0.0, 0.0]])
    scales = np.zeros((1, 3))
    opacities = np.array([20.0])

    _, no_cameras = compute_plan_point_cloud(
        means, scales, opacities, np.zeros(3), np.eye(3), 1.0, 0.0
    )
    _, camera_at_floor = compute_plan_point_cloud(
        means,
        scales,
        opacities,
        np.zeros(3),
        np.eye(3),
        1.0,
        0.0,
        camera_positions=np.array([[0.0, 0.0, 0.0]]),
    )
    _, no_points = compute_plan_point_cloud(
        np.zeros((0, 3)),
        np.zeros((0, 3)),
        np.zeros(0),
        np.zeros(3),
        np.eye(3),
        1.0,
        0.0,
        camera_positions=np.array([[0.0, 0.0, 5.0]]),
    )

    assert no_cameras is None
    assert camera_at_floor is None
    assert no_points is None


def _write_splat_ply(
    path: Path,
    means: np.ndarray,
    scales: np.ndarray,
    opacities: np.ndarray,
) -> None:
    vertices = np.zeros(
        means.shape[0],
        dtype=[
            ("x", "f4"),
            ("y", "f4"),
            ("z", "f4"),
            ("scale_0", "f4"),
            ("scale_1", "f4"),
            ("scale_2", "f4"),
            ("opacity", "f4"),
        ],
    )
    vertices["x"] = means[:, 0]
    vertices["y"] = means[:, 1]
    vertices["z"] = means[:, 2]
    vertices["scale_0"] = scales[:, 0]
    vertices["scale_1"] = scales[:, 1]
    vertices["scale_2"] = scales[:, 2]
    vertices["opacity"] = opacities
    PlyData([PlyElement.describe(vertices, "vertex")]).write(path)


def _fake_geometric_data() -> ColmapGeometricData:
    return ColmapGeometricData(
        center=[0.0, 0.0, 0.0],
        world_rotation=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        radius=2.0,
        positions=[[0.0, 0.0, 5.0]],
    )


def test_generate_plan_point_cloud_writes_artifacts_next_to_splat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "PLAN_DENSITY_THRESHOLD", 1.0)
    monkeypatch.setattr(
        "api.lib.compute.colmap_geometric_data.colmap_compute_geometric_data",
        lambda sparse_dir: _fake_geometric_data(),
    )

    splat_path = tmp_path / "splat.ply"
    means, scales, opacities = _make_splat_arrays()
    _write_splat_ply(splat_path, means, scales, opacities)

    generate_plan_point_cloud(splat_path, tmp_path / "colmap")
    generate_plan_point_cloud(splat_path, tmp_path / "colmap")

    binary_path = splat_path.with_name(POINT_CLOUD_BINARY_FILENAME)
    meta_path = splat_path.with_name(POINT_CLOUD_META_FILENAME)

    expected = np.array([[1.0, 2.0, 2.0], [-4.0, 0.5, 2.0]], dtype="<f4")
    assert binary_path.read_bytes() == expected.tobytes()
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        ["splat.ply", POINT_CLOUD_BINARY_FILENAME, POINT_CLOUD_META_FILENAME]
    )

    meta = json.loads(meta_path.read_text())
    assert meta["count"] == 2
    assert meta["bounds"] == [[-4.0, 0.5, 2.0], [1.0, 2.0, 2.0]]
    assert meta["cm_per_unit"] == pytest.approx(170.0 * 0.9 / 3.0)
