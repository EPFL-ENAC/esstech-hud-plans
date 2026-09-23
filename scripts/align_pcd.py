"""Rotate and rescale a COLMAP dense point cloud for SpatialLM.

SpatialLM expects a z-up, roughly metric point cloud with the floor near
z = 0. A COLMAP reconstruction has an arbitrary world frame: any rotation
and an unknown scale. This script uses the COLMAP camera path (from the
sparse model) to estimate the gravity axis, then uses a vertical histogram
of the dense cloud to find the floor plane, and rescales the scene so the
distance between the camera plane and the floor plane equals the physical
camera height.

Standalone script: it does not import from the codebase. The rotation logic
is ported from ``colmap_compute_geometric_data`` in
``backend/api/lib/compute/colmap_geometric_data.py`` (fit a plane through
the camera centers by eigendecomposition of their covariance; the smallest
eigenvector is the up axis, signed by the average camera up vector).

Usage:
    uv run align_pcd.py fused.ply sparse/0 out.ply --camera-height 1.6
"""

from pathlib import Path

import numpy as np
import open3d as o3d
import pycolmap
import typer

app = typer.Typer(help=__doc__, no_args_is_help=True)


def compute_camera_path_rotation(
    sparse_dir: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Estimate the gravity-aligned frame from the COLMAP camera path.

    Returns ``(path_center, world_rotation, camera_centers)`` where
    ``world_rotation`` has the new x, y, z axes as its columns (z = up).
    Rotated points are ``(points - path_center) @ world_rotation``, which
    equals ``world_rotation.T @ (points - path_center)`` per point.

    Ported from ``colmap_compute_geometric_data`` in
    ``backend/api/lib/compute/colmap_geometric_data.py``.
    """
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

    positions = np.array(positions)
    average_up = np.mean(up_vectors, axis=0)

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


@app.command()
def main(
    fused_ply: Path = typer.Argument(
        ..., help="Input dense point cloud from COLMAP (e.g. dense/fused.ply)."
    ),
    sparse_dir: Path = typer.Argument(
        ..., help="COLMAP sparse model directory (images.bin, cameras.bin)."
    ),
    output: Path = typer.Argument(..., help="Output aligned PLY path."),
    camera_height: float = typer.Option(
        ...,
        "--camera-height",
        help="Physical camera height above the floor, in meters.",
    ),
    bins: int = typer.Option(
        256, "--bins", help="Number of vertical histogram bins for floor search."
    ),
) -> None:
    """Align a COLMAP fused.ply to z-up and scale it to meters."""
    if camera_height <= 0:
        raise typer.BadParameter("--camera-height must be positive.")
    if bins < 1:
        raise typer.BadParameter("--bins must be at least 1.")

    cloud = o3d.io.read_point_cloud(str(fused_ply))
    if not cloud.has_points() or len(cloud.points) == 0:
        raise typer.BadParameter(f"Input cloud {fused_ply} has no points.")

    points = np.asarray(cloud.points, dtype=np.float64)
    path_center, world_rotation, camera_centers = compute_camera_path_rotation(
        sparse_dir
    )

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

    scale = camera_height / span

    # Uniform scale about the path center, then drop the floor to z = 0.
    aligned_points = scale * rotated_points
    aligned_points[:, 2] -= scale * floor_level

    cloud.points = o3d.utility.Vector3dVector(aligned_points)
    if cloud.has_normals():
        normals = np.asarray(cloud.normals, dtype=np.float64) @ world_rotation
        cloud.normals = o3d.utility.Vector3dVector(normals)

    output.parent.mkdir(parents=True, exist_ok=True)
    if not o3d.io.write_point_cloud(str(output), cloud, write_ascii=False):
        raise typer.Exit(code=1, message=f"Failed to write {output}")

    print(f"Registered images:   {len(camera_centers)}")
    print(f"Path center:         {np.array2string(path_center, precision=4)}")
    print(f"Camera level (z):    {camera_level:.4f}")
    print(f"Floor level (z):     {floor_level:.4f} (peak bin: {floor_points} pts)")
    print(f"Scale:               {scale:.4f}")
    print(f"Camera height out:   {scale * span:.4f}")
    print(f"Wrote:               {output}")


if __name__ == "__main__":
    app()
