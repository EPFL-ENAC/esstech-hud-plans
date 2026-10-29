import json
import threading
from pathlib import Path

import numpy as np
import pytest
from plyfile import PlyData, PlyElement

from api.config import config
from api.lib.compute import point_cloud as point_cloud_compute
from api.lib.compute.colmap_geometric_data import ColmapGeometricData
from api.lib.compute.point_cloud import (
    POINT_CLOUD_BINARY_FILENAME,
    POINT_CLOUD_META_FILENAME,
    compute_plan_point_cloud,
    generate_plan_point_cloud,
    generate_plan_point_cloud_if_missing,
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


def test_compute_plan_point_cloud_drops_non_finite_positions() -> None:
    means = np.array(
        [
            [1.0, 2.0, 2.0],
            [np.nan, 0.0, 0.0],
            [0.0, 0.0, np.inf],
            [-4.0, 0.5, 2.0],
        ]
    )
    scales = np.zeros((4, 3))
    opacities = np.full(4, 20.0)
    camera_positions = np.array([[0.0, 0.0, 5.0]])

    positions, cm_per_unit = compute_plan_point_cloud(
        means,
        scales,
        opacities,
        center=np.zeros(3),
        world_rotation=np.eye(3),
        radius=1.0,
        threshold=0.0,
        camera_positions=camera_positions,
    )

    np.testing.assert_allclose(positions, [[1.0, 2.0, 2.0], [-4.0, 0.5, 2.0]])
    assert cm_per_unit == pytest.approx(170.0 * 0.9 / 3.0)

    empty_positions, no_scale = compute_plan_point_cloud(
        means[[1, 2]],
        scales[:2],
        opacities[:2],
        center=np.zeros(3),
        world_rotation=np.eye(3),
        radius=1.0,
        threshold=0.0,
        camera_positions=camera_positions,
    )

    assert empty_positions.shape == (0, 3)
    assert no_scale is None


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


def _setup_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str = "splat.ply",
) -> tuple[Path, Path]:
    monkeypatch.setattr(config, "PLAN_DENSITY_THRESHOLD", 1.0)
    monkeypatch.setattr(
        "api.lib.compute.colmap_geometric_data.colmap_compute_geometric_data",
        lambda sparse_dir: _fake_geometric_data(),
    )
    splat_path = tmp_path / name
    means, scales, opacities = _make_splat_arrays()
    _write_splat_ply(splat_path, means, scales, opacities)
    return splat_path, tmp_path / "colmap"


def test_generate_plan_point_cloud_if_missing_generates_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    splat_path, colmap_directory = _setup_generation(tmp_path, monkeypatch)

    generate_plan_point_cloud_if_missing(splat_path, colmap_directory)

    assert splat_path.with_name(POINT_CLOUD_BINARY_FILENAME).is_file()
    assert splat_path.with_name(POINT_CLOUD_META_FILENAME).is_file()


def test_generate_plan_point_cloud_if_missing_skips_existing_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    splat_path = tmp_path / "splat.ply"
    splat_path.with_name(POINT_CLOUD_BINARY_FILENAME).write_bytes(b"bin")
    splat_path.with_name(POINT_CLOUD_META_FILENAME).write_bytes(b"{}")

    def fail(splat_path: Path, colmap_directory: Path) -> None:
        raise AssertionError("must not regenerate existing artifacts")

    monkeypatch.setattr(point_cloud_compute, "generate_plan_point_cloud", fail)

    generate_plan_point_cloud_if_missing(splat_path, tmp_path / "colmap")


def test_generate_plan_point_cloud_if_missing_propagates_generation_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    splat_path = tmp_path / "splat.ply"
    splat_path.write_bytes(b"not a ply")

    def fail(splat_path: Path, colmap_directory: Path) -> None:
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(point_cloud_compute, "generate_plan_point_cloud", fail)

    with pytest.raises(RuntimeError, match="conversion failed"):
        generate_plan_point_cloud_if_missing(splat_path, tmp_path / "colmap")


def test_generate_plan_point_cloud_if_missing_single_flights_concurrent_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    splat_path, colmap_directory = _setup_generation(tmp_path, monkeypatch)
    started = threading.Event()
    release = threading.Event()
    calls: list[Path] = []
    original = point_cloud_compute.generate_plan_point_cloud

    def blocking_generate(splat_path: Path, colmap_directory: Path) -> None:
        calls.append(splat_path)
        started.set()
        assert release.wait(timeout=30), "generation was never released"
        original(splat_path, colmap_directory)

    monkeypatch.setattr(
        point_cloud_compute, "generate_plan_point_cloud", blocking_generate
    )
    results: list[Exception | None] = []

    def call() -> None:
        try:
            generate_plan_point_cloud_if_missing(splat_path, colmap_directory)
            results.append(None)
        except Exception as exc:  # pragma: no cover - failure reporting
            results.append(exc)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for thread in threads:
        thread.start()
    try:
        assert started.wait(timeout=30), "generation never started"
        assert len(calls) == 1
        release.set()
    finally:
        for thread in threads:
            thread.join(timeout=30)

    assert results == [None, None]
    assert calls == [splat_path]
    assert splat_path.with_name(POINT_CLOUD_BINARY_FILENAME).is_file()


def test_generate_plan_point_cloud_if_missing_does_not_block_other_splats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, first_colmap = _setup_generation(tmp_path, monkeypatch, name="a.ply")
    second, second_colmap = _setup_generation(tmp_path, monkeypatch, name="b.ply")
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()

    def generate_a(splat_path: Path, colmap_directory: Path) -> None:
        first_started.set()
        assert release_first.wait(timeout=30), "first generation was never released"
        splat_path.with_name(POINT_CLOUD_BINARY_FILENAME).write_bytes(b"bin")
        splat_path.with_name(POINT_CLOUD_META_FILENAME).write_bytes(b"{}")

    def generate_b(splat_path: Path, colmap_directory: Path) -> None:
        second_started.set()
        splat_path.with_name(POINT_CLOUD_BINARY_FILENAME).write_bytes(b"bin")
        splat_path.with_name(POINT_CLOUD_META_FILENAME).write_bytes(b"{}")

    def patch(name: str, replacement: object) -> None:
        monkeypatch.setattr(point_cloud_compute, name, replacement)

    patch("generate_plan_point_cloud", generate_a)
    first_thread = threading.Thread(
        target=generate_plan_point_cloud_if_missing, args=(first, first_colmap)
    )
    first_thread.start()
    try:
        assert first_started.wait(timeout=30), "first generation never started"
        patch("generate_plan_point_cloud", generate_b)
        second_thread = threading.Thread(
            target=generate_plan_point_cloud_if_missing, args=(second, second_colmap)
        )
        second_thread.start()
        assert second_started.wait(timeout=30), (
            "second splat was blocked by the first generation"
        )
        release_first.set()
        second_thread.join(timeout=30)
    finally:
        release_first.set()
        first_thread.join(timeout=30)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert first.with_name(POINT_CLOUD_BINARY_FILENAME).is_file()
    assert second.with_name(POINT_CLOUD_BINARY_FILENAME).is_file()
