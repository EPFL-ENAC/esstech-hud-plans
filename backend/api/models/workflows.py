from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

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


class ColmapSettings(BaseModel):
    data_type: Literal["individual", "video", "internet"] = "video"
    quality: Literal["low", "medium", "high", "extreme"] = "low"
    camera_model: Literal["PINHOLE", "OPENCV", "OPENCV_FISHEYE", "RADIAL"] = "OPENCV"
    single_camera: bool = True
    use_gpu: bool = False
    use_global_mapper: bool = False


class BrushSettings(BaseModel):
    total_steps: int = Field(default=10_000, gt=0)
    render_mode: Literal["default", "mip"] = "default"
    sh_degree: int = Field(default=3, ge=0, le=3)
    max_splats: int = Field(default=10_000_000, gt=0)
    refine_every: int = Field(default=200, gt=0)
    growth_grad_threshold: float = Field(default=0.0025, gt=0)
    growth_stop_iter: int = Field(default=15_000, ge=0)
    max_resolution: int = Field(default=1920, gt=0)
    subsample_frames: int = Field(default=1, gt=0)
    alpha_mode: Literal["masked", "transparent"] = "transparent"
    export_every: int = Field(default=5_000, gt=0)


class SplatGenerationWorkflowSettings(BaseModel):
    ffmpeg: FfmpegSettings = Field(
        default_factory=FfmpegSettings,
        description="Settings for the ffmpeg frame-extraction task.",
    )
    colmap: ColmapSettings = Field(
        default_factory=ColmapSettings,
        description="Settings for the COLMAP sparse-reconstruction task.",
    )
    brush: BrushSettings = Field(
        default_factory=BrushSettings,
        description="Settings for the Brush Gaussian-splat training task.",
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
