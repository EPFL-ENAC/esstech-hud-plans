import json
import os
from pathlib import Path

import numpy as np

from api.config import config

CAMERAMAN_HEIGHT_CM = 170.0
# Assume the camera sits at 90% of the cameraman height
CAMERA_HEIGHT_FRACTION = 0.9
FLOOR_HISTOGRAM_BINS = 300

POINT_CLOUD_BINARY_FILENAME = "point-cloud.bin"
POINT_CLOUD_META_FILENAME = "point-cloud.meta.json"


def compute_plan_point_cloud(
    means: np.ndarray,
    scales: np.ndarray,
    opacities: np.ndarray,
    center: np.ndarray,
    world_rotation: np.ndarray,
    radius: float,
    threshold: float,
    camera_positions: np.ndarray | None = None,
) -> tuple[np.ndarray, float | None]:
    """Filter splats by decoded density and bake positions into the plan frame.

    The 3DGS PLY stores opacity as a logit and scales as log-scales; the
    frontend filter sees Spark-decoded values (sigmoid/exp), so decode the
    same way and keep splats with density >= threshold * radius**3. The plan
    frame is world_rotation.T @ (p - center): the frontend transposes
    world_rotation before applying it to the centered position.
    """
    center = np.asarray(center, dtype=np.float64)
    world_rotation = np.asarray(world_rotation, dtype=np.float64)
    means = np.asarray(means, dtype=np.float64)
    scales = np.asarray(scales, dtype=np.float64)
    opacities = np.asarray(opacities, dtype=np.float64).reshape(-1)

    with np.errstate(over="ignore"):
        decoded_opacities = 1.0 / (1.0 + np.exp(-opacities))
    decoded_scales = np.exp(scales)
    densities = decoded_opacities / np.prod(decoded_scales, axis=-1)
    keep = densities >= threshold * radius**3

    plan_positions = (world_rotation.T @ (means[keep] - center).T).T
    floor_z = _floor_z_offset(plan_positions)
    cm_per_unit = _cm_per_unit(camera_positions, center, world_rotation, floor_z)
    return plan_positions.astype(np.float32), cm_per_unit


def _floor_z_offset(plan_positions: np.ndarray) -> float | None:
    """Mode of the plan-frame z histogram, as frontend autoDetectFloorOffset."""
    if plan_positions.size == 0:
        return None
    z_values = plan_positions[:, 2]
    min_z = float(np.min(z_values))
    max_z = float(np.max(z_values))
    bin_size = (max_z - min_z) / FLOOR_HISTOGRAM_BINS
    if bin_size == 0:
        return min_z
    indices = np.minimum(
        np.floor((z_values - min_z) / bin_size).astype(np.int64),
        FLOOR_HISTOGRAM_BINS - 1,
    )
    counts = np.bincount(indices, minlength=FLOOR_HISTOGRAM_BINS)
    mode_bin = int(np.argmax(counts))
    return min_z + mode_bin * bin_size + bin_size / 2


def _cm_per_unit(
    camera_positions: np.ndarray | None,
    center: np.ndarray,
    world_rotation: np.ndarray,
    floor_z: float | None,
) -> float | None:
    """Frontend scale-bar heuristic: cameraman height over camera-to-floor distance."""
    if camera_positions is None or len(camera_positions) == 0 or floor_z is None:
        return None
    camera_positions = np.asarray(camera_positions, dtype=np.float64)
    plan_cameras = (world_rotation.T @ (camera_positions - center).T).T
    height = float(np.mean(plan_cameras[:, 2])) - floor_z
    if height == 0:
        return None
    return CAMERAMAN_HEIGHT_CM * CAMERA_HEIGHT_FRACTION / height


def generate_plan_point_cloud(splat_path: Path, colmap_directory: Path) -> None:
    """Write the plan point cloud artifacts next to the trained splat."""
    try:
        from plyfile import PlyData

        from api.lib.compute.colmap_geometric_data import (
            colmap_compute_geometric_data,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Required libraries for the point cloud conversion are missing. "
            "Please install the [blueprint] extras."
        ) from exc

    plydata = PlyData.read(splat_path)
    vertex = plydata["vertex"]
    means = np.stack([vertex["x"], vertex["y"], vertex["z"]], axis=-1)
    scales = np.stack(
        [vertex["scale_0"], vertex["scale_1"], vertex["scale_2"]], axis=-1
    )
    opacities = np.asarray(vertex["opacity"], dtype=np.float64)

    geometric_data = colmap_compute_geometric_data(
        str(colmap_directory / "sparse" / "0")
    )
    positions, cm_per_unit = compute_plan_point_cloud(
        means,
        scales,
        opacities,
        np.asarray(geometric_data.center),
        np.asarray(geometric_data.world_rotation),
        geometric_data.radius,
        config.PLAN_DENSITY_THRESHOLD,
        camera_positions=np.asarray(geometric_data.positions),
    )

    if positions.shape[0] == 0:
        bounds = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    else:
        bounds = [
            [float(value) for value in positions.min(axis=0)],
            [float(value) for value in positions.max(axis=0)],
        ]
    meta = {
        "count": int(positions.shape[0]),
        "bounds": bounds,
        "cm_per_unit": cm_per_unit,
    }

    _atomic_write(
        splat_path.with_name(POINT_CLOUD_BINARY_FILENAME),
        positions.astype("<f4").tobytes(order="C"),
    )
    _atomic_write(
        splat_path.with_name(POINT_CLOUD_META_FILENAME),
        json.dumps(meta).encode("utf-8"),
    )


def _atomic_write(path: Path, data: bytes) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    try:
        temp_path.write_bytes(data)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
