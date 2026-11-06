"""Wall-aligned heading for the plan frame, from the top-down point layout."""

import numpy as np

# A fixed grid keeps the sweep cost constant. Both axes span the same square box,
# which covers every rotation, so a bin is always the same width and scores stay
# comparable from one angle to the next.
SWEEP_BINS = 256
SWEEP_STEP_RADIANS = np.deg2rad(1.0)
SWEEP_STEPS = round(np.pi / 2 / SWEEP_STEP_RADIANS)
MAX_SWEEP_POINTS = 200_000


def align_plan_frame(points_xy: np.ndarray) -> np.ndarray:
    """Plan-frame rotation about Z that aligns the walls with the plan axes.

    The sweep only fixes the heading modulo a quarter turn, which gives four
    equally wall-aligned rotations. They are ranked twice: the longer side of
    the layout goes to Y, then the direction of today's X axis is kept, so a
    plan never flips end for end for no reason.
    """
    points_xy = np.asarray(points_xy, dtype=np.float64)
    if points_xy.shape[0] < 2:
        return np.eye(4)

    base = _dominant_wall_angle(points_xy)
    covariance = np.cov(points_xy, rowvar=False, bias=True)
    best_rotation = np.eye(4)
    best_score = -np.inf
    for quarter in range(4):
        rotation = _rotation_z(base + quarter * np.pi / 2)
        # Rows of the rotation are the new axes expressed in today's frame.
        x_axis = rotation[0, :2]
        y_axis = rotation[1, :2]
        long_side_y = y_axis @ covariance @ y_axis >= x_axis @ covariance @ x_axis
        forward = y_axis[0] if abs(y_axis[0]) >= abs(y_axis[1]) else y_axis[1]
        score = (2.0 if long_side_y else 0.0) + (1.0 if forward > 0 else 0.0)
        if score > best_score:
            best_score = score
            best_rotation = rotation
    return best_rotation


def _dominant_wall_angle(points_xy: np.ndarray) -> float:
    """Rotation that makes the top-down layout pile into the fewest bins."""
    points = _subsample(points_xy)
    points = points - points.mean(axis=0)
    extent = float(np.sqrt(np.square(points).sum(axis=1)).max())
    if not np.isfinite(extent) or extent <= 0:
        return 0.0
    limits = (-extent, extent)

    best_angle = 0.0
    best_score = -np.inf
    for step in range(SWEEP_STEPS):
        angle = step * SWEEP_STEP_RADIANS
        cos, sin = np.cos(angle), np.sin(angle)
        columns = points[:, 0] * cos - points[:, 1] * sin
        rows = points[:, 0] * sin + points[:, 1] * cos
        score = _concentration(columns, limits) + _concentration(rows, limits)
        if score > best_score:
            best_score = score
            best_angle = float(angle)
    return best_angle


def _concentration(values: np.ndarray, limits: tuple[float, float]) -> float:
    """How much of the mass sits in few bins; 1.0 when it all shares one bin."""
    counts = np.histogram(values, bins=SWEEP_BINS, range=limits)[0]
    total = counts.sum()
    if total == 0:
        return 0.0
    weights = counts / total
    return float(np.sum(weights**2))


def _subsample(points_xy: np.ndarray) -> np.ndarray:
    step = max(1, -(-points_xy.shape[0] // MAX_SWEEP_POINTS))
    return points_xy[::step]


def _rotation_z(angle: float) -> np.ndarray:
    cos, sin = np.cos(angle), np.sin(angle)
    rotation = np.eye(4)
    rotation[:2, :2] = [[cos, -sin], [sin, cos]]
    return rotation
