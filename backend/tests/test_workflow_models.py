import pytest
from api.models.workflows import (
    BrushSettings,
    ColmapSettings,
    FfmpegSettings,
    FramePickerSettings,
    SplatGenerationWorkflowSettings,
)
from pydantic import ValidationError


def test_splat_generation_workflow_settings_defaults_are_grouped_by_tool() -> None:
    settings = SplatGenerationWorkflowSettings()

    assert settings.ffmpeg == FfmpegSettings(
        fps=2.0,
        fit_in_width=1920,
        fit_in_height=1920,
    )
    assert settings.frame_picker is None
    assert settings.colmap == ColmapSettings(
        data_type="video",
        quality="low",
        camera_model="OPENCV",
        single_camera=True,
        use_gpu=False,
        use_global_mapper=False,
    )
    assert settings.brush == BrushSettings(
        total_steps=10_000,
        render_mode="default",
        sh_degree=3,
        max_splats=10_000_000,
        refine_every=200,
        growth_grad_threshold=0.0025,
        growth_stop_iter=15_000,
        max_resolution=1920,
        subsample_frames=1,
        alpha_mode="transparent",
        export_every=5_000,
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
def test_colmap_settings_reject_unsupported_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        ColmapSettings(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total_steps", 0),
        ("render_mode", "cinematic"),
        ("sh_degree", 4),
        ("max_splats", 0),
        ("refine_every", 0),
        ("growth_grad_threshold", 0),
        ("growth_stop_iter", -1),
        ("max_resolution", 0),
        ("subsample_frames", 0),
        ("alpha_mode", "opaque"),
        ("export_every", 0),
    ],
)
def test_brush_settings_reject_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        BrushSettings.model_validate({field: value})
