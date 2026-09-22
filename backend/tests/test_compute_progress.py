import pytest
from api.lib.compute.progress import (
    BrushProgressEstimator,
    ColmapProgressEstimator,
    FfmpegProgressEstimator,
)


def test_ffmpeg_remembers_duration_and_ignores_unknown_timestamps() -> None:
    estimator = FfmpegProgressEstimator()
    assert estimator.feed("frame=10 time=00:00:01.0") is None
    assert estimator.feed("Duration: 00:00:10.00, start: 0.0") is None
    assert estimator.feed("frame=10 time=N/A") is None
    assert estimator.feed("\x1b[32mframe=10 time=00:00:02.50\x1b[0m") == 0.25
    assert estimator.feed("frame=100 time=00:00:12.00") == 1.0
    assert estimator.feed("muxing overhead: unknown") is None


def test_ffmpeg_rejects_zero_duration() -> None:
    estimator = FfmpegProgressEstimator()
    estimator.feed("Duration: 00:00:00.00")
    assert estimator.feed("time=00:00:01.00") is None


def test_colmap_combines_extraction_matching_and_mapping() -> None:
    estimator = ColmapProgressEstimator()
    assert estimator.feed("Feature extraction") is None
    assert estimator.feed("Processed file [10/100]") == pytest.approx(0.03)
    assert estimator.feed("Processed file [100/100]") == pytest.approx(0.30)
    assert estimator.feed("Feature matching & geometric verification") == 0.35
    assert estimator.feed("incremental_pipeline.cc Registering image") == 0.40
    assert estimator.feed("\x1b[2Knum_reg_frames=50") == pytest.approx(0.70)
    assert estimator.feed("num_reg_frames=101") == 1.0
    assert estimator.feed("Keeping successful reconstruction") is None


def test_colmap_handles_missing_counts_and_unrecognized_global_mapping() -> None:
    estimator = ColmapProgressEstimator()
    assert estimator.feed("num_reg_frames=2") is None
    assert estimator.feed("Processed file [0/0]") is None
    assert estimator.feed("num_reg_frames=2") is None
    assert estimator.feed("Global positioning") is None


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ("\x1b[2KTraining 250/1000 Steps [10s]", 0.25),
        ("1000 / 1000 steps", 1.0),
        ("1001/1000 Steps", 1.0),
        ("0/0 Steps", None),
        ("Completed loading", None),
        ("Training took 30s", None),
        ("evaluating every 100 steps", None),
    ],
)
def test_brush_only_uses_training_step_counts(
    record: str, expected: float | None
) -> None:
    assert BrushProgressEstimator().feed(record) == expected
