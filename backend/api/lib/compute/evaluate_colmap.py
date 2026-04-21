from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

import pycolmap
from api.utils.colmap_utils import looks_like_colmap_model_dir
from api.utils.maths import (
    MeanMedianMinMax,
    StatisticsSummary,
    clamp01,
    contiguous_segments,
    fraction_leq,
)
from pydantic import BaseModel


class ReprojectionErrorFracs(BaseModel):
    le_1px: float
    le_2px: float
    le_4px: float

    @staticmethod
    def from_errors(errors: list[float]) -> ReprojectionErrorFracs:
        return ReprojectionErrorFracs(
            le_1px=fraction_leq(errors, 1.0),
            le_2px=fraction_leq(errors, 2.0),
            le_4px=fraction_leq(errors, 4.0),
        )


class ReconstructionMetrics(BaseModel):
    model_name: str
    model_path: str

    num_registered_images: int
    registered_fraction: float

    num_points3D: int
    num_observations: int

    track_length: MeanMedianMinMax
    points3D_per_image: MeanMedianMinMax

    reprojection_error_stats: StatisticsSummary
    reprojection_error_fracs: ReprojectionErrorFracs

    first_registered_frame: int | None
    last_registered_frame: int | None
    temporal_span: int | None
    longest_contiguous_run: int
    num_temporal_segments: int
    registered_fraction_within_span: float | None


RECONSTRUCTION_EVALUATION_WEIGHTS = {
    "coverage_score": 0.6,
    "continuity_score": 0.1,
    "accuracy_score": 0.2,
    "points_density_score": 0.1,
}


class ReconstructionEvaluation(BaseModel):
    metrics: ReconstructionMetrics

    score: float

    coverage_score: float
    continuity_score: float
    accuracy_score: float
    points_density_score: float
    fragmentation: float

    @staticmethod
    def from_metrics(metrics: ReconstructionMetrics) -> ReconstructionEvaluation:
        coverage_score = metrics.registered_fraction
        continuity_score = (
            metrics.longest_contiguous_run / metrics.temporal_span
            if metrics.temporal_span and metrics.temporal_span > 0
            else 0.0
        )
        accuracy_score = 1.0 - clamp01(
            ((metrics.reprojection_error_stats.median or 0.0) / 5.0) ** 2
        )
        points_density_score = clamp01(math.log1p(metrics.num_points3D / 2_000) ** 2)

        fragmentation = 0.05 * max(metrics.num_temporal_segments - 1, 0)

        score = (
            RECONSTRUCTION_EVALUATION_WEIGHTS["coverage_score"] * coverage_score
            + RECONSTRUCTION_EVALUATION_WEIGHTS["continuity_score"] * continuity_score
            + RECONSTRUCTION_EVALUATION_WEIGHTS["accuracy_score"] * accuracy_score
            + RECONSTRUCTION_EVALUATION_WEIGHTS["points_density_score"]
            * points_density_score
            - fragmentation
        )

        return ReconstructionEvaluation(
            metrics=metrics,
            score=score,
            coverage_score=coverage_score,
            continuity_score=continuity_score,
            accuracy_score=accuracy_score,
            points_density_score=points_density_score,
            fragmentation=fragmentation,
        )


class SparseEvaluation(BaseModel):
    sparse_path: Path
    total_input_frames: int | None
    num_models: int
    evaluations: list[ReconstructionEvaluation]
    best_model_index: int


def evaluate_sparse_reconstructions(
    sparse_dir: str | Path,
    total_input_frames: int | None = None,
    frame_index_fn: Callable[[str], int | None] | None = None,
) -> SparseEvaluation:
    """
    Evaluate every COLMAP sparse reconstruction under a `sparse/` directory.

    Expected layout:
        sparse/
          0/
            cameras.bin
            images.bin
            points3D.bin
          1/
            ...
          ...

    Args:
        sparse_dir:
            Path to the COLMAP `sparse/` directory.
        total_input_frames:
            Total number of video frames/images given to COLMAP. If provided,
            registered_fraction is computed against this total. If omitted,
            registered_fraction will be 1.0 for each model if the model has
            registered images, because the denominator is unknown.
        frame_index_fn:
            Optional function mapping image filename -> frame index.
            If omitted, a default parser extracts all digits from the filename
            stem. Example: "frame_000123.jpg" -> 123.

    Returns:
        SparseEvaluation dataclass containing one ReconstructionMetrics per
        sparse submodel.

    Notes:
        - This implementation is intentionally defensive because pycolmap
          attribute names can vary slightly by version.
        - Temporal continuity metrics depend on filenames encoding frame order.
    """
    sparse_path = Path(sparse_dir).expanduser().resolve()
    if not sparse_path.exists():
        raise FileNotFoundError(f"Sparse directory not found: {sparse_path}")
    if not sparse_path.is_dir():
        raise NotADirectoryError(f"Expected directory: {sparse_path}")

    frame_index_fn = frame_index_fn or _default_frame_index_parser

    model_dirs = sorted(
        [
            p
            for p in sparse_path.iterdir()
            if p.is_dir() and looks_like_colmap_model_dir(p)
        ],
        key=lambda p: _natural_model_sort_key(p.name),
    )

    metrics = [
        _evaluate_one_model(
            model_dir=model_dir,
            total_input_frames=total_input_frames,
            frame_index_fn=frame_index_fn,
        )
        for model_dir in model_dirs
    ]

    evaluations = [ReconstructionEvaluation.from_metrics(m) for m in metrics]

    best_index = 0
    for i, e in enumerate(evaluations):
        if e.score > evaluations[best_index].score:
            best_index = i

    return SparseEvaluation(
        sparse_path=sparse_path,
        total_input_frames=total_input_frames,
        num_models=len(evaluations),
        evaluations=evaluations,
        best_model_index=best_index,
    )


def _evaluate_one_model(
    model_dir: Path,
    total_input_frames: int | None,
    frame_index_fn: Callable[[str], int | None],
) -> ReconstructionMetrics:
    recon = pycolmap.Reconstruction(str(model_dir))

    images = list(recon.images.values())
    points3D = list(recon.points3D.values())

    registered_images = [img for img in images if img.has_pose]
    num_registered_images = len(registered_images)

    if total_input_frames is not None and total_input_frames > 0:
        registered_fraction = num_registered_images / total_input_frames
    else:
        registered_fraction = 1.0 if num_registered_images > 0 else 0.0

    reproj_errors: list[float] = [p.error for p in points3D if p.error != -1.0]
    track_lengths: list[int] = [
        len(p.track.elements) for p in points3D if p.track.elements is not None
    ]
    total_observations = sum(track_lengths)

    frame_indices: list[int] = []
    for img in registered_images:
        idx = frame_index_fn(img.name)
        if idx is not None:
            frame_indices.append(idx)

    points3D_per_image = [img.num_points3D for img in registered_images]

    segments = contiguous_segments(frame_indices)
    longest_run = max((b - a + 1) for a, b in segments) if segments else 0
    first_frame = min(frame_indices) if frame_indices else None
    last_frame = max(frame_indices) if frame_indices else None
    temporal_span = (
        (last_frame - first_frame + 1)
        if first_frame is not None and last_frame is not None
        else None
    )
    registered_fraction_within_span = (
        num_registered_images / temporal_span
        if temporal_span is not None and temporal_span > 0
        else None
    )

    return ReconstructionMetrics(
        model_name=model_dir.name,
        model_path=str(model_dir),
        num_registered_images=num_registered_images,
        registered_fraction=registered_fraction,
        num_points3D=len(points3D),
        num_observations=total_observations,
        track_length=MeanMedianMinMax.from_values(track_lengths),
        points3D_per_image=MeanMedianMinMax.from_values(points3D_per_image),
        reprojection_error_stats=StatisticsSummary.from_values(reproj_errors),
        reprojection_error_fracs=ReprojectionErrorFracs.from_errors(reproj_errors),
        first_registered_frame=first_frame,
        last_registered_frame=last_frame,
        temporal_span=temporal_span,
        longest_contiguous_run=longest_run,
        num_temporal_segments=len(segments),
        registered_fraction_within_span=registered_fraction_within_span,
    )


def _natural_model_sort_key(name: str) -> tuple[int, int | str]:
    try:
        return (0, int(name))
    except ValueError:
        return (1, name)


def _default_frame_index_parser(image_name: str) -> int | None:
    stem = Path(image_name).stem
    digits = "".join(ch for ch in stem if ch.isdigit())
    return int(digits) if digits else None
