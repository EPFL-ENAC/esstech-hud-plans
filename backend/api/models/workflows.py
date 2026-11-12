from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

WorkflowStatus = Literal[
    "scheduled",
    "pending",
    "running",
    "completed",
    "failed",
    "cancelled",
    "crashed",
    "paused",
    "cancelling",
]


class FfmpegSettings(BaseModel):
    fps: float = Field(default=2.0, gt=0)
    fit_in_width: int = Field(default=1920, gt=0)
    fit_in_height: int = Field(default=1920, gt=0)


class FramePickerSettings(BaseModel):
    min_fps: int = Field(default=1, gt=0)
    distance_threshold: float = Field(default=0.2, ge=0)
    remove_outliers: bool = True
    outlier_sharpness_ratio: float = Field(default=0.1, ge=0, le=1)


class ObjectMaskSettings(BaseModel):
    enabled: bool = False
    prompts: list[str] = Field(default_factory=list)

    @field_validator("prompts")
    @classmethod
    def _strip_prompts(cls, prompts: list[str]) -> list[str]:
        return [stripped for prompt in prompts if (stripped := prompt.strip())]

    @model_validator(mode="after")
    def _require_prompt_when_enabled(self) -> "ObjectMaskSettings":
        if self.enabled and not self.prompts:
            raise ValueError("at least one object prompt is required when enabled")
        return self


class SpirulaSfmSettings(BaseModel):
    data_type: Literal["individual", "video", "internet"] = "video"
    pairs: Literal["auto", "exhaustive", "sequential", "prefilter"] = "exhaustive"
    quality: Literal["low", "medium", "high", "extreme"] = "low"
    camera_model: Literal[
        "simple-pinhole", "pinhole", "radial", "opencv", "opencv-fisheye"
    ] = "opencv"
    single_camera: bool = True
    remove_objects: ObjectMaskSettings = Field(
        default_factory=lambda: ObjectMaskSettings(prompts=["person"]),
    )


class SpirulaGeometrySettings(BaseModel):
    compute_depth: bool = False
    compute_normals: bool = False


class SpirulaTrainSettings(BaseModel):
    num_iterations: int = Field(default=30_000, gt=0)
    quality: Literal["low", "medium", "high", "ultra"] = "medium"
    primitive: Literal["3dgs", "mip"] = "3dgs"
    sh_degree: int = Field(default=3, ge=0, le=3)
    cap_max: int = Field(default=1_000_000, gt=0)
    floater_suppression: bool = True
    meshing_preset: bool = True
    keep_objects: ObjectMaskSettings = Field(
        default_factory=lambda: ObjectMaskSettings(
            prompts=["walls", "doors", "windows", "floor", "ceiling"]
        ),
    )


class SplatGenerationWorkflowSettings(BaseModel):
    ffmpeg: FfmpegSettings = Field(
        default_factory=FfmpegSettings,
        description="Settings for the ffmpeg frame-extraction task.",
    )
    frame_picker: FramePickerSettings | None = Field(
        default=None,
        description="Optional settings for movement- and sharpness-based frame selection.",
    )
    spirula_sfm: SpirulaSfmSettings = Field(
        default_factory=SpirulaSfmSettings,
        description="Settings for the spirula sparse-reconstruction task.",
    )
    spirula_geometry: SpirulaGeometrySettings = Field(
        default_factory=SpirulaGeometrySettings,
        description="Settings for the spirula depth- and normal-map prediction task.",
    )
    spirula_train: SpirulaTrainSettings = Field(
        default_factory=SpirulaTrainSettings,
        description="Settings for the spirula Gaussian-splat training task.",
    )


class WorkflowSubmissionResponse(BaseModel):
    workflow_id: UUID


class WorkflowStatusResponse(BaseModel):
    workflow_id: UUID
    status: WorkflowStatus
    message: str | None = None


class SplatGenerationResultResponse(BaseModel):
    frames_directory: str
    colmap_directory: str
    splat_path: str
