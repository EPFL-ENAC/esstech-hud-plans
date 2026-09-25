"""Rotate, rescale and vertically align a point cloud for SpatialLM.

SpatialLM expects a z-up, roughly metric point cloud with the floor near
z = 0. A COLMAP reconstruction has an arbitrary world frame: any rotation
and an unknown scale. This script uses the camera path to estimate the
gravity axis, then uses a vertical histogram of the dense cloud to find the
floor plane, and rescales the scene so the distance between the camera
plane and the floor plane equals the physical camera height.

The camera path comes from either a COLMAP sparse model or a TUM-format
camera trajectory file (e.g. written by a MASt3R-SLAM run). With --keep-scale
no rescale happens for an already metric cloud; the scene is still rotated to
z-up and the floor is dropped to z = 0.

Standalone script: it does not import from the codebase. The rotation logic
is ported from ``colmap_compute_geometric_data`` in
``backend/api/lib/compute/colmap_geometric_data.py`` (fit a plane through
the camera centers by eigendecomposition of their covariance; the smallest
eigenvector is the up axis, signed by the average camera up vector).

Usage:
    python align_pcd.py main fused.ply sparse/0 -o out.ply --camera-height 1.6
    python align_pcd.py main cloud.ply -o out.ply --traj traj.txt --keep-scale
"""

from pathlib import Path

import numpy as np
import open3d as o3d
import typer

app = typer.Typer(help=__doc__, no_args_is_help=True)


def load_tum_trajectory(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load camera centers and up vectors from a TUM-format trajectory.

    Each line holds ``<timestamp> <x> <y> <z> <qx> <qy> <qz> <qw>``; x y z is
    the camera center in world and the quaternion is the world-from-camera
    rotation (lietorch SE3 packed t then quat, scalar-last). Lines with fewer
    than seven numeric fields are skipped. Returns ``(centers, up_vectors)``
    with the camera up direction equal to ``rotation @ [0, -1, 0]`` per pose
    (OpenCV camera y points down).
    """
    rot_from_quat = None
    try:
        from scipy.spatial.transform import Rotation

        rot_from_quat = Rotation.from_quat
    except ImportError:
        pass

    positions = []
    up_vectors = []
    for raw in path.read_text().splitlines():
        tokens = raw.split()
        if len(tokens) < 7:
            continue
        values = []
        for token in tokens:
            try:
                values.append(float(token))
            except ValueError:
                continue
        if len(values) < 7:
            continue
        # a timestamp line has 8 numbers, keep the last 7 (t + quat)
        x, y, z, qx, qy, qz, qw = values[-7:]
        positions.append([x, y, z])
        if rot_from_quat is not None:
            up = rot_from_quat([qx, qy, qz, qw]).apply([0.0, -1.0, 0.0])
        else:
            up = quat_rotate_vector(qx, qy, qz, qw, [0.0, -1.0, 0.0])
        up_vectors.append(up)
    if not positions:
        raise typer.BadParameter(f"No trajectory poses found in {path}")
    return np.array(positions), np.array(up_vectors)


def quat_rotate_vector(qx: float, qy: float, qz: float, qw: float,
                       vector) -> list:
    """Rotate a vector by a scalar-last quaternion (numpy fallback)."""
    quat = np.array([qx, qy, qz, qw], dtype=np.float64)
    quat = quat / np.linalg.norm(quat)
    x, y, z, w = quat
    rotation = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    return list(rotation @ np.asarray(vector, dtype=np.float64))


def compute_camera_path_rotation(
    sparse_dir: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Estimate the gravity-aligned frame from the COLMAP camera path.

    Thin wrapper: it loads the COLMAP model and feeds the shared plane-fit
    logic in ``compute_camera_path_rotation_from``, so the old COLMAP usage
    keeps working bit-for-bit.

    Returns ``(path_center, world_rotation, camera_centers)`` where
    ``world_rotation`` has the new x, y, z axes as its columns (z = up).
    Rotated points are ``(points - path_center) @ world_rotation``, which
    equals ``world_rotation.T @ (points - path_center)`` per point.

    Ported from ``colmap_compute_geometric_data`` in
    ``backend/api/lib/compute/colmap_geometric_data.py``.
    """
    import pycolmap

    reconstruction = pycolmap.Reconstruction(str(sparse_dir))

    positions = []
    up_vectors = []
    for image_id in sorted(reconstruction.images.keys()):
        image = reconstruction.images[image_id]
        pose = image.cam_from_world()

        translation = pose.translation
        rotation = pose.rotation.matrix()

        # Camera center in world coordinates. COLMAP camera axes are
        # right-down-forward, so the camera up direction is -y.
        positions.append(-rotation.T @ translation)
        up_vectors.append(-rotation.T @ np.array([0.0, 1.0, 0.0]))

    if not positions:
        raise typer.BadParameter(
            f"No registered images with poses found in {sparse_dir}"
        )

    return compute_camera_path_rotation_from(
        np.array(positions), np.array(up_vectors)
    )


def compute_camera_path_rotation_from(
    centers: np.ndarray, up_vectors: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit the gravity axis through camera centers (shared plane-fit part).

    Works for a COLMAP camera path or any loaded camera trajectory. Returns
    ``(path_center, world_rotation, centers)`` with identical math to the
    former COLMAP-only path: the up axis is the smallest eigenvector of the
    camera center covariance, signed by the average camera up vector.
    """
    positions = np.asarray(centers, dtype=np.float64)
    if len(positions) == 0:
        raise typer.BadParameter("No camera poses to fit the gravity axis")
    average_up = np.mean(np.asarray(up_vectors, dtype=np.float64), axis=0)

    # Find the normal to a plane fitted to the camera positions.
    path_center = np.mean(positions, axis=0)
    centered_positions = positions - path_center
    cov = np.cov(centered_positions, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    normal = eigenvectors[:, np.argmin(eigenvalues)]
    tangent = eigenvectors[:, np.argmax(eigenvalues)]
    normal *= np.sign(np.dot(normal, average_up))
    normal /= np.linalg.norm(normal)
    world_rotation = np.stack([tangent, np.cross(normal, tangent), normal], axis=1)

    return path_center, world_rotation, positions


def find_floor_height(
    heights: np.ndarray, camera_level: float, num_bins: int
) -> tuple[float, int]:
    """Find the floor height from the peak of a vertical histogram.

    Only bins whose center lies under ``camera_level`` are considered; the
    densest of them is assumed to be the floor. Returns the mean height of
    the points inside that bin and the bin's point count.
    """
    counts, edges = np.histogram(heights, bins=num_bins)
    centers = 0.5 * (edges[:-1] + edges[1:])
    below = np.flatnonzero(centers < camera_level)
    if below.size == 0:
        raise typer.BadParameter(
            "No histogram bins below the camera path level; the floor plane "
            "cannot be found. Is the camera path at the bottom of the cloud?"
        )

    peak_bin = below[np.argmax(counts[below])]
    in_bin = (heights >= edges[peak_bin]) & (heights <= edges[peak_bin + 1])
    if np.any(in_bin):
        floor = float(heights[in_bin].mean())
    else:
        floor = float(centers[peak_bin])
    return floor, int(counts[peak_bin])


def find_wall_alignment_angle(
    xy: np.ndarray, step_deg: float = 0.5, bins: int = 128
) -> float:
    """Estimate the rotation angle that aligns walls with the x and y axes.

    Scans the rotation angle over [0, 90) degrees. For each angle it builds a
    top-down histogram of the rotated xy coordinates and scores the axis
    concentration: the sum of squared row sums plus the sum of squared column
    sums. Walls that run along x or y concentrate their mass in few rows and
    columns, so the histogram score peaks at the aligned angle. The scan is
    periodic over 90 degrees, which covers both wall directions of a
    rectangular room layout.

    Returns the angle in degrees; rotate the points by it to align the walls.
    """
    if len(xy) == 0:
        raise typer.BadParameter("Cannot estimate a wall angle from 0 points")
    if step_deg <= 0 or 90 % step_deg != 0:
        raise typer.BadParameter("--step-deg must divide 90 evenly (e.g. 0.5)")
    centered = xy - xy.mean(axis=0)
    extent = float(np.abs(centered).max()) + 1e-6
    best_deg = 0.0
    best_score = -1.0
    for deg in np.arange(0.0, 90.0, step_deg):
        angle = np.radians(deg)
        c, s = np.cos(angle), np.sin(angle)
        r0 = centered[:, 0] * c - centered[:, 1] * s
        r1 = centered[:, 0] * s + centered[:, 1] * c
        hist, _, _ = np.histogram2d(
            r0, r1, bins=bins,
            range=[[-extent, extent], [-extent, extent]],
        )
        score = float((hist.sum(axis=1) ** 2).sum() + (hist.sum(axis=0) ** 2).sum())
        if score > best_score:
            best_score = score
            best_deg = float(deg)
    return best_deg


def rotate_z(points: np.ndarray, deg: float) -> np.ndarray:
    """Rotate the xy coordinates of a point array around the z axis.

    The rotation happens about the xy centroid and leaves z untouched.
    """
    angle = np.radians(deg)
    c, s = np.cos(angle), np.sin(angle)
    rot = np.array([[c, -s], [s, c]])
    center = points[:, :2].mean(axis=0)
    out = points.copy()
    out[:, :2] = (points[:, :2] - center) @ rot.T + center
    return out


@app.command()
def main(
    fused_ply: Path = typer.Argument(
        ..., help="Input dense point cloud from COLMAP or any video SLAM run."
    ),
    sparse_dir: Path | None = typer.Argument(
        None, help="COLMAP sparse model directory (images.bin, cameras.bin)."
    ),
    output: Path = typer.Option(
        ...,
        "-o", "--output",
        help="Output aligned PLY path.",
    ),
    traj: Path | None = typer.Option(
        None, "--traj",
        help="TUM-format camera trajectory file (timestamp x y z qx qy qz qw), "
        "e.g. from a MASt3R-SLAM run; used instead of the COLMAP sparse model.",
    ),
    camera_height: float | None = typer.Option(
        None,
        "--camera-height",
        help="Physical camera height above the floor, in meters. "
        "Required unless --keep-scale is set.",
    ),
    keep_scale: bool = typer.Option(
        False, "--keep-scale",
        help="Keep the input scale (metric cloud, e.g. from the MASt3R metric "
        "checkpoint); still rotate to z-up and drop the floor to z = 0.",
    ),
    bins: int = typer.Option(
        256, "--bins", help="Number of vertical histogram bins for floor search."
    ),
    no_xy_align: bool = typer.Option(
        False, "--no-xy-align",
        help="Skip the final z-axis rotation that aligns walls with x and y.",
    ),
    flip_up: bool = typer.Option(
        False, "--flip-up",
        help="Turn the fitted gravity axis 180 degrees. Use when the whole "
        "reconstruction is upside down, e.g. when the source frames were "
        "upside down because the decoder ignored the container rotation flag.",
    ),
    step_deg: float = typer.Option(
        0.5, "--step-deg", help="Wall angle scan step in degrees."
    ),
) -> None:
    """Align a point cloud to z-up and optionally rescale it to meters."""
    if (sparse_dir is None) == (traj is None):
        raise typer.BadParameter(
            "Give exactly one of the COLMAP sparse model dir or --traj."
        )
    if camera_height is not None and camera_height <= 0:
        raise typer.BadParameter("--camera-height must be positive.")
    if keep_scale and camera_height is not None:
        raise typer.BadParameter(
            "--camera-height is unused with --keep-scale; drop it."
        )
    if not keep_scale and camera_height is None:
        raise typer.BadParameter(
            "--camera-height is required unless --keep-scale is set."
        )
    if bins < 1:
        raise typer.BadParameter("--bins must be at least 1.")

    cloud = o3d.io.read_point_cloud(str(fused_ply))
    if not cloud.has_points() or len(cloud.points) == 0:
        raise typer.BadParameter(f"Input cloud {fused_ply} has no points.")

    points = np.asarray(cloud.points, dtype=np.float64)
    if traj is not None:
        positions, up_vectors = load_tum_trajectory(traj)
        path_center, world_rotation, camera_centers = (
            compute_camera_path_rotation_from(positions, up_vectors)
        )
    else:
        path_center, world_rotation, camera_centers = compute_camera_path_rotation(
            sparse_dir
        )

    if flip_up:
        # 180-degree turn about the y axis of the fitted frame: negate the
        # tangent and up columns so the rotation stays proper (det = +1) and
        # the height along the fitted normal changes sign.
        world_rotation = world_rotation * np.array([-1.0, 1.0, -1.0])

    # Rotate the scene so z points up along the camera path normal.
    rotated_points = (points - path_center) @ world_rotation
    rotated_cameras = (camera_centers - path_center) @ world_rotation
    camera_level = float(np.median(rotated_cameras[:, 2]))

    floor_level, floor_points = find_floor_height(
        rotated_points[:, 2], camera_level, bins
    )
    span = camera_level - floor_level
    if span <= 0:
        raise typer.BadParameter(
            "The floor plane is not under the camera path "
            f"(camera level {camera_level:.4f}, floor level {floor_level:.4f})."
        )

    if keep_scale:
        # native scale kept; span is the implied camera height in these units
        scale = 1.0
    else:
        scale = camera_height / span

    # Uniform scale about the path center, then drop the floor to z = 0.
    aligned_points = scale * rotated_points
    aligned_points[:, 2] -= scale * floor_level

    wall_deg = 0.0
    if not no_xy_align:
        # last step: rotate around the z axis so walls align with x and y
        wall_deg = find_wall_alignment_angle(aligned_points[:, :2], step_deg=step_deg)
        aligned_points = rotate_z(aligned_points, wall_deg)

    cloud.points = o3d.utility.Vector3dVector(aligned_points)
    if cloud.has_normals():
        normals = np.asarray(cloud.normals, dtype=np.float64) @ world_rotation
        if not no_xy_align:
            angle = np.radians(wall_deg)
            c, s = np.cos(angle), np.sin(angle)
            nx = normals[:, 0] * c - normals[:, 1] * s
            normals[:, 1] = normals[:, 0] * s + normals[:, 1] * c
            normals[:, 0] = nx
        cloud.normals = o3d.utility.Vector3dVector(normals)

    output.parent.mkdir(parents=True, exist_ok=True)
    if not o3d.io.write_point_cloud(str(output), cloud, write_ascii=False):
        raise typer.Exit(code=1, message=f"Failed to write {output}")

    print(f"Registered images:   {len(camera_centers)}")
    print(f"Path center:         {np.array2string(path_center, precision=4)}")
    print(f"Camera level (z):    {camera_level:.4f}")
    print(f"Floor level (z):     {floor_level:.4f} (peak bin: {floor_points} pts)")
    print(f"Scale:               {scale:.4f}")
    print(f"Wall angle rot:      {wall_deg:.2f} deg (x/y alignment)")
    print(f"Camera height out:   {scale * span:.4f}")
    if flip_up:
        print("Up axis:             flipped (--flip-up)")
    print(f"Wrote:               {output}")


@app.command()
def xy_align(
    input_ply: Path = typer.Argument(
        ..., help="Input z-aligned point cloud (e.g. aligned.ply)."
    ),
    output: Path = typer.Argument(..., help="Output wall-aligned PLY path."),
    step_deg: float = typer.Option(
        0.5, "--step-deg", help="Wall angle scan step in degrees."
    ),
    bins: int = typer.Option(128, "--bins", help="Histogram bins for the angle scan."),
) -> None:
    """Rotate an already z-aligned cloud around z so walls align with x and y."""
    cloud = o3d.io.read_point_cloud(str(input_ply))
    if not cloud.has_points() or len(cloud.points) == 0:
        raise typer.BadParameter(f"Input cloud {input_ply} has no points.")

    points = np.asarray(cloud.points, dtype=np.float64)
    points = points[np.isfinite(points).all(axis=1)]
    if len(points) == 0:
        raise typer.BadParameter(f"Input cloud {input_ply} has no finite points.")

    wall_deg = find_wall_alignment_angle(points[:, :2], step_deg=step_deg, bins=bins)
    points = rotate_z(points, wall_deg)
    cloud.points = o3d.utility.Vector3dVector(points)
    if cloud.has_normals():
        normals = np.asarray(cloud.normals, dtype=np.float64)
        angle = np.radians(wall_deg)
        c, s = np.cos(angle), np.sin(angle)
        nx = normals[:, 0] * c - normals[:, 1] * s
        normals[:, 1] = normals[:, 0] * s + normals[:, 1] * c
        normals[:, 0] = nx
        cloud.normals = o3d.utility.Vector3dVector(normals)

    output.parent.mkdir(parents=True, exist_ok=True)
    if not o3d.io.write_point_cloud(str(output), cloud, write_ascii=False):
        raise typer.Exit(code=1, message=f"Failed to write {output}")

    print(f"Wall angle rot:      {wall_deg:.2f} deg (x/y alignment)")
    print(f"Points:               {len(points)}")
    print(f"Wrote:               {output}")


if __name__ == "__main__":
    app()
