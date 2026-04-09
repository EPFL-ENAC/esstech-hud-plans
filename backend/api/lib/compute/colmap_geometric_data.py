import numpy as np
import pycolmap
from pydantic import BaseModel


class ColmapGeometricData(BaseModel):
    center: list[float]
    world_rotation: list[list[float]]
    radius: float
    positions: list[list[float]]


def colmap_compute_geometric_data(sparse_dir: str):
    reconstruction = pycolmap.Reconstruction(sparse_dir)
    positions = []
    up_vectors = []

    sorted_image_ids = sorted(reconstruction.images.keys())

    for image_id in sorted_image_ids:
        image = reconstruction.images[image_id]
        pose = image.cam_from_world()

        translation = pose.translation
        rotation = pose.rotation.matrix()

        positions.append(-rotation.T @ translation)
        up_vectors.append(-rotation.T @ np.array([0, 1, 0]))

    positions = np.array(positions)
    up_vectors = np.array(up_vectors)
    average_up = np.mean(up_vectors, axis=0)

    # Find the normal to a plane fitted to the camera positions
    center = np.mean(positions, axis=0)
    centered_positions = positions - center
    cov = np.cov(centered_positions, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eig(cov)
    normal = eigenvectors[:, np.argmin(eigenvalues)]
    tangent = eigenvectors[:, np.argmax(eigenvalues)]
    normal *= np.sign(np.dot(normal, average_up))
    normal /= np.linalg.norm(normal)
    world_rotation = np.stack([tangent, np.cross(normal, tangent), normal], axis=1)
    radius = np.max(np.linalg.norm(centered_positions, axis=1))

    return ColmapGeometricData(
        center=center.tolist(),
        world_rotation=world_rotation.tolist(),
        radius=radius,
        positions=positions.tolist(),
    )


def compute_blueprint_view_matrix(
    colmap_geometry: ColmapGeometricData, distance_scale: float = 1000.0
) -> np.ndarray:
    """Compute the 4x4 view matrix for the blueprint top-down view.

    Args:
        colmap_geometry: `ColmapGeometricData` containing:
            - `center`: scene center as ``[x, y, z]``
            - `world_rotation`: 3x3 world rotation matrix
            - `radius`: scene radius used to place the top-down camera
            - `positions`: camera positions as ``[[x, y, z], ...]``
        distance_scale: Multiplier for radius to determine view distance (default: 1000.0)

    Returns:
        4x4 numpy array representing the view matrix
    """
    center = np.array(colmap_geometry.center)
    world_rotation = np.array(colmap_geometry.world_rotation)
    radius = colmap_geometry.radius

    D = distance_scale * radius  # Large distance to flatten perspective

    # Top-down view rotation matrix (converts from world space to top-down view)
    R_td = np.array([[1, 0, 0], [0, -1, 0], [0, 0, 1]], dtype=np.float32)
    R_combined = R_td @ world_rotation.T
    t_combined = -R_combined @ center
    t_combined[2] += D

    view_mat = np.eye(4, dtype=np.float32)
    view_mat[:3, :3] = R_combined
    view_mat[:3, 3] = t_combined

    return view_mat
