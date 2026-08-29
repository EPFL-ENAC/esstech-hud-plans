import pytest
from api.models.workflows import FrameExtractionSettings
from pydantic import ValidationError


def test_frame_extraction_settings_defaults() -> None:
    settings = FrameExtractionSettings()

    assert settings.fps == 2.0
    assert settings.fit_in_width == 1920
    assert settings.fit_in_height == 1920


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
        FrameExtractionSettings(**{field: value})
