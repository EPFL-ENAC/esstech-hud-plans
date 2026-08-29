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


class FrameExtractionSettings(BaseModel):
    fps: float = Field(default=2.0, gt=0)
    fit_in_width: int = Field(default=1920, gt=0)
    fit_in_height: int = Field(default=1920, gt=0)


class WorkflowSubmissionResponse(BaseModel):
    workflow_id: UUID


class WorkflowStatusResponse(BaseModel):
    workflow_id: UUID
    status: WorkflowStatus
    message: str | None = None


class FrameExtractionResultResponse(BaseModel):
    frames_directory: str
