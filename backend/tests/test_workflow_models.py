import pytest
from pydantic import ValidationError

from api.models.workflows import (
    FfmpegSettings,
    FramePickerSettings,
    SpirulaSfmSettings,
    SpirulaTrainSettings,
    SplatGenerationWorkflowSettings,
)


def test_splat_generation_workflow_settings_defaults_are_grouped_by_tool() -> None:
    settings = SplatGenerationWorkflowSettings()

    assert settings.ffmpeg == FfmpegSettings(
        fps=2.0,
        fit_in_width=1920,
        fit_in_height=1920,
    )
    assert settings.frame_picker is None
    assert settings.spirula_sfm == SpirulaSfmSettings(
        data_type="video",
        quality="low",
        camera_model="opencv",
        single_camera=True,
    )
    assert settings.spirula_train == SpirulaTrainSettings(
        num_iterations=30_000,
        quality="medium",
        primitive="3dgs",
        sh_degree=3,
        cap_max=1_000_000,
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


def test_frame_picker_settings_defaults() -> None:
    assert FramePickerSettings() == FramePickerSettings(
        min_fps=1,
        distance_threshold=0.2,
        remove_outliers=True,
        outlier_sharpness_ratio=0.1,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("min_fps", 0),
        ("distance_threshold", -0.1),
        ("outlier_sharpness_ratio", -0.1),
        ("outlier_sharpness_ratio", 1.1),
    ],
)
def test_frame_picker_settings_reject_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        FramePickerSettings.model_validate({field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("data_type", "archive"),
        ("quality", "maximum"),
        ("camera_model", "SIMPLE_RADIAL"),
    ],
)
def test_spirula_sfm_settings_reject_unsupported_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        SpirulaSfmSettings(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("num_iterations", 0),
        ("quality", "maximum"),
        ("primitive", "2dgs"),
        ("sh_degree", 4),
        ("sh_degree", -1),
        ("cap_max", 0),
    ],
)
def test_spirula_train_settings_reject_invalid_values(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        SpirulaTrainSettings.model_validate({field: value})
