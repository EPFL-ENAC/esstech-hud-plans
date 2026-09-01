import pytest
from api.models.workflows import (
    ColmapSettings,
    FfmpegSettings,
    FrameExtractionWorkflowSettings,
)
from pydantic import ValidationError


def test_frame_extraction_workflow_settings_defaults_are_grouped_by_tool() -> None:
    settings = FrameExtractionWorkflowSettings()

    assert settings.ffmpeg == FfmpegSettings(
        fps=2.0,
        fit_in_width=1920,
        fit_in_height=1920,
    )
    assert settings.colmap == ColmapSettings(
        data_type="video",
        quality="low",
        camera_model="OPENCV",
        single_camera=True,
        use_gpu=False,
        use_global_mapper=False,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fps", 0),
        ("fps", -1),
        ("fit_in_width", 0),
        ("fit_in_height", -1),
    ],
)
def test_frame_extraction_settings_require_positive_values(
    field: str, value: int
) -> None:
    with pytest.raises(ValidationError):
        FfmpegSettings(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("data_type", "archive"),
        ("quality", "maximum"),
        ("camera_model", "SIMPLE_RADIAL"),
    ],
)
def test_colmap_settings_reject_unsupported_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        ColmapSettings(**{field: value})
