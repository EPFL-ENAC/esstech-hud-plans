import logging

import numpy as np
import pycolmap
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# A pose farther than this factor times the 95th-percentile camera distance is
# a bogus registration (e.g. a blurry frame registered far away); keeping it
# inflates the radius, center and plane fit used by every consumer below.
OUTLIER_DISTANCE_PERCENTILE = 95
OUTLIER_DISTANCE_FACTOR = 3.0


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
    positions, up_vectors = _reject_outlier_poses(positions, up_vectors)
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


def _reject_outlier_poses(
    positions: np.ndarray, up_vectors: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Drop camera poses that sit far outside the reconstruction.

    COLMAP occasionally registers a frame at a wildly wrong position (weak
    parallax, blurry frame) while most cameras stay together. The cutoff is 3
    times the 95th-percentile distance from the median pose, so it can never
    reject more than the top 5% of cameras and continuous camera paths survive.
    """
    if len(positions) < 2:
        return positions, up_vectors
    distances = np.linalg.norm(positions - np.median(positions, axis=0), axis=1)
    cutoff = OUTLIER_DISTANCE_FACTOR * np.percentile(
        distances, OUTLIER_DISTANCE_PERCENTILE
    )
    keep = distances <= cutoff
    if keep.all():
        return positions, up_vectors
    logger.warning(
        "Rejected %d COLMAP camera pose(s) farther than %.2f units from the scene",
        int((~keep).sum()),
        cutoff,
    )
    return positions[keep], up_vectors[keep]
