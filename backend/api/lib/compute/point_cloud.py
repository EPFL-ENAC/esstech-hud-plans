import json
import logging
import os
import threading
from pathlib import Path

import numpy as np

from api.config import config

CAMERAMAN_HEIGHT_CM = 170.0
# Assume the camera sits at 90% of the cameraman height
CAMERA_HEIGHT_FRACTION = 0.9
FLOOR_HISTOGRAM_BINS = 300

POINT_CLOUD_BINARY_FILENAME = "point-cloud.bin"
POINT_CLOUD_META_FILENAME = "point-cloud.meta.json"

# One lock per splat path ever generated on demand; the count stays small per process.
_POINT_CLOUD_LOCKS: dict[str, threading.Lock] = {}
_POINT_CLOUD_LOCKS_GUARD = threading.Lock()

logger = logging.getLogger(__name__)


def transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Apply a 4x4 rigid transform to (N, 3) points."""
    matrix = np.asarray(matrix, dtype=np.float64)
    return np.asarray(points, dtype=np.float64) @ matrix[:3, :3].T + matrix[:3, 3]


def compute_plan_point_cloud(
    means: np.ndarray,
    scales: np.ndarray,
    opacities: np.ndarray,
    matrix: np.ndarray,
    radius: float,
    threshold: float,
) -> np.ndarray:
    """Filter splats by decoded density and bake positions into the plan frame.

    The 3DGS PLY stores opacity as a logit and scales as log-scales; the
    frontend filter sees Spark-decoded values (sigmoid/exp), so decode the
    same way and keep splats with density >= threshold * radius**3. The plan
    frame comes from ``plan_matrix``: the same matrix the viewers apply, so
    the point cloud and the splat cannot disagree. Trained splats can hold
    non-finite positions, and a degenerate reconstruction makes the whole
    frame non-finite, so drop them.
    """
    means = np.asarray(means, dtype=np.float64)
    scales = np.asarray(scales, dtype=np.float64)
    opacities = np.asarray(opacities, dtype=np.float64).reshape(-1)

    with np.errstate(over="ignore"):
        decoded_opacities = 1.0 / (1.0 + np.exp(-opacities))
    decoded_scales = np.exp(scales)
    densities = decoded_opacities / np.prod(decoded_scales, axis=-1)
    keep = densities >= threshold * radius**3

    plan_positions = transform_points(means[keep], matrix)
    plan_positions = plan_positions[np.isfinite(plan_positions).all(axis=1)]
    return plan_positions.astype(np.float32)


def floor_z_offset(plan_positions: np.ndarray) -> float | None:
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


def plan_scale(
    plan_positions: np.ndarray,
    plan_camera_positions: np.ndarray | None,
) -> float | None:
    """Frontend scale-bar heuristic: cameraman height over camera-to-floor distance."""
    floor_z = floor_z_offset(plan_positions)
    if floor_z is None or plan_camera_positions is None:
        return None
    plan_camera_positions = np.asarray(plan_camera_positions, dtype=np.float64)
    if len(plan_camera_positions) == 0:
        return None
    height = float(np.mean(plan_camera_positions[:, 2])) - floor_z
    if height == 0:
        return None
    return CAMERAMAN_HEIGHT_CM * CAMERA_HEIGHT_FRACTION / height


def read_plan_positions(splat_path: Path) -> np.ndarray:
    """Plan-frame positions baked next to the splat, as (N, 3) floats."""
    path = splat_path.with_name(POINT_CLOUD_BINARY_FILENAME)
    if not path.is_file():
        return np.zeros((0, 3), dtype=np.float32)
    return np.frombuffer(path.read_bytes(), dtype="<f4").reshape(-1, 3)


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
            "Please install the backend dependencies with `uv sync`."
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
    positions = compute_plan_point_cloud(
        means,
        scales,
        opacities,
        geometric_data.matrix,
        geometric_data.radius,
        config.PLAN_DENSITY_THRESHOLD,
    )

    if positions.shape[0] == 0:
        bounds = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
        logger.warning(
            "Plan point cloud for %s is empty: every splat was filtered out "
            "(threshold=%g, %d splats considered)",
            splat_path,
            config.PLAN_DENSITY_THRESHOLD * geometric_data.radius**3,
            len(means),
        )
    else:
        bounds = [
            [float(value) for value in positions.min(axis=0)],
            [float(value) for value in positions.max(axis=0)],
        ]
    meta = {
        "count": int(positions.shape[0]),
        "bounds": bounds,
    }

    _atomic_write(
        splat_path.with_name(POINT_CLOUD_BINARY_FILENAME),
        positions.astype("<f4").tobytes(order="C"),
    )
    _atomic_write(
        splat_path.with_name(POINT_CLOUD_META_FILENAME),
        json.dumps(meta).encode("utf-8"),
    )


def plan_point_cloud_artifacts_exist(splat_path: Path) -> bool:
    """Both artifacts are written together, so their joint presence means done."""
    return (
        splat_path.with_name(POINT_CLOUD_BINARY_FILENAME).is_file()
        and splat_path.with_name(POINT_CLOUD_META_FILENAME).is_file()
    )


def generate_plan_point_cloud_if_missing(
    splat_path: Path,
    colmap_directory: Path,
) -> None:
    """Generate the artifacts once when missing, single-flight per splat path.

    ``_atomic_write`` uses a fixed temp path, so concurrent generations for the
    same splat would corrupt the artifacts; they serialize on a per-splat lock
    instead, so different splats never block each other.
    """
    if plan_point_cloud_artifacts_exist(splat_path):
        return
    with _POINT_CLOUD_LOCKS_GUARD:
        lock = _POINT_CLOUD_LOCKS.setdefault(str(splat_path), threading.Lock())
    with lock:
        if plan_point_cloud_artifacts_exist(splat_path):
            return
        generate_plan_point_cloud(splat_path, colmap_directory)


def _atomic_write(path: Path, data: bytes) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    try:
        temp_path.write_bytes(data)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
