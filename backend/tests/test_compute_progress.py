import pytest

from api.lib.compute.progress import (
    FfmpegProgressEstimator,
    SpirulaMaskProgressEstimator,
    SpirulaSfmProgressEstimator,
    SpirulaTrainProgressEstimator,
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


def test_sfm_combines_extraction_matching_and_mapping() -> None:
    estimator = SpirulaSfmProgressEstimator()
    assert estimator.feed("Loading model...") is None
    assert estimator.feed("1/42   frame_00001.jpg   Features: 823") == pytest.approx(
        0.25 / 42
    )
    assert estimator.feed(
        "\x1b[2K42/42   frame_00042.jpg   Features: 1000"
    ) == pytest.approx(0.25)
    assert estimator.feed("12/40 pairs matched") == pytest.approx(0.325)
    assert estimator.feed(
        "Registered image 1; images in the model: 1"
    ) == pytest.approx(0.5 + 0.5 / 42)
    assert estimator.feed("images in the model: 42") == pytest.approx(1.0)
    assert estimator.feed("RESULT: OK") is None


def test_sfm_handles_missing_counts() -> None:
    estimator = SpirulaSfmProgressEstimator()
    assert estimator.feed("images in the model: 5") == 0.50
    assert estimator.feed("0/0 pairs matched") is None
    assert estimator.feed("0/0   frame_00000.jpg   Features: 0") is None


def test_mask_progress_covers_each_pass_without_regressing() -> None:
    estimator = SpirulaMaskProgressEstimator(total_frames=4, pass_count=2)

    assert estimator.feed("Loading model...") is None
    assert estimator.feed("frame 0: frame_00001.jpg -- kept 95.0%") == pytest.approx(
        0.125
    )
    assert estimator.feed(
        "\x1b[2Kframe 3: frame_00004.jpg -- kept 90.0%"
    ) == pytest.approx(0.5)
    assert estimator.feed(
        "frames: 4 in 2.0 s -- 500 ms per frame (decode 10, model 480, write 10)"
    ) == pytest.approx(0.5)
    assert estimator.feed("frame 0: frame_00001.jpg -- kept 95.0%") == pytest.approx(
        0.625
    )
    assert estimator.feed("frame 3: frame_00004.jpg -- kept 90.0%") == pytest.approx(
        1.0
    )
    assert estimator.feed(
        "frames: 4 in 1.0 s -- 250 ms per frame (decode 10, model 230, write 10)"
    ) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ("step   3000/30000  ( 10%)  splats 50000", 0.1),
        ("step  30000/30000  (100%)  splats 900000", 1.0),
        ("\x1b[2Kstep  15000/30000  ( 50%)  splats 900000", 0.5),
        ("Loading config", None),
        ("Saving splat.ply", None),
        ("no training steps here", None),
    ],
)
def test_train_only_uses_training_step_percentages(
    record: str, expected: float | None
) -> None:
    assert SpirulaTrainProgressEstimator().feed(record) == expected
