import numpy as np
import pytest

from api.lib.compute.plan_orientation import align_plan_frame


def _room(half_width: float, half_depth: float, angle: float) -> np.ndarray:
    """Dense wall points of a rectangular room, rotated by ``angle``."""
    steps = 300
    sides = [
        np.linspace([-half_width, -half_depth], [half_width, -half_depth], steps),
        np.linspace([half_width, -half_depth], [half_width, half_depth], steps),
        np.linspace([half_width, half_depth], [-half_width, half_depth], steps),
        np.linspace([-half_width, half_depth], [-half_width, -half_depth], steps),
    ]
    points = np.concatenate(sides)
    cos, sin = np.cos(angle), np.sin(angle)
    return points @ np.array([[cos, sin], [-sin, cos]])


def test_align_plan_frame_turns_the_long_side_onto_y() -> None:
    angle = np.deg2rad(30.0)
    long_axis = np.array([np.cos(angle), np.sin(angle)])

    rotation = align_plan_frame(_room(half_width=8.0, half_depth=3.0, angle=angle))

    np.testing.assert_allclose(rotation[:2, :2] @ long_axis, [0.0, 1.0], atol=0.02)
    # Today's X points at (1, 0), and the long side inherits that direction.
    assert long_axis[0] > 0


def test_align_plan_frame_is_a_rotation_about_z() -> None:
    rotation = align_plan_frame(_room(6.0, 2.0, np.deg2rad(-17.0)))

    assert rotation[2].tolist() == [0.0, 0.0, 1.0, 0.0]
    assert rotation[:3, 3].tolist() == [0.0, 0.0, 0.0]
    np.testing.assert_allclose(
        rotation[:3, :3] @ rotation[:3, :3].T, np.eye(3), atol=1e-12
    )
    assert np.linalg.det(rotation[:3, :3]) == pytest.approx(1.0)


def test_align_plan_frame_keeps_an_already_aligned_room() -> None:
    rotation = align_plan_frame(_room(half_width=8.0, half_depth=3.0, angle=0.0))

    np.testing.assert_allclose(rotation[:2, :2], [[0.0, -1.0], [1.0, 0.0]], atol=0.02)


def test_align_plan_frame_needs_two_points() -> None:
    np.testing.assert_allclose(align_plan_frame(np.zeros((0, 2))), np.eye(4))
    np.testing.assert_allclose(align_plan_frame(np.zeros((1, 2))), np.eye(4))
