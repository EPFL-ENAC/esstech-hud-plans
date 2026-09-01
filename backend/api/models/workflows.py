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


class FrameExtractionWorkflowSettings(BaseModel):
    ffmpeg: FfmpegSettings = Field(
        default_factory=FfmpegSettings,
        description="Settings for the ffmpeg frame-extraction task.",
    )
    colmap: ColmapSettings = Field(
        default_factory=ColmapSettings,
        description="Settings for the COLMAP sparse-reconstruction task.",
    )


class WorkflowSubmissionResponse(BaseModel):
    workflow_id: UUID


class WorkflowStatusResponse(BaseModel):
    workflow_id: UUID
    status: WorkflowStatus
    message: str | None = None


class FrameExtractionResultResponse(BaseModel):
    frames_directory: str
    colmap_directory: str
