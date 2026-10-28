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
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    normal = eigenvectors[:, np.argmin(eigenvalues)]
    tangent = eigenvectors[:, np.argmax(eigenvalues)]
    normal *= np.sign(np.dot(normal, average_up))
    normal /= np.linalg.norm(normal)
    world_rotation = np.stack([tangent, np.cross(normal, tangent), normal], axis=1).real
    radius = np.max(np.linalg.norm(centered_positions, axis=1))

    return ColmapGeometricData(
        center=center.tolist(),
        world_rotation=world_rotation.tolist(),
        radius=radius,
        positions=positions.tolist(),
    )
