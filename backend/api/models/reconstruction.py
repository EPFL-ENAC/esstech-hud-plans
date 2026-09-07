from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from api.models.user import utc_now
from api.models.workflows import SplatGenerationWorkflowSettings
from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, CheckConstraint, Column, DateTime, String
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from api.models.building import Building


class ReconstructionStatus(StrEnum):
    PREPARING = "preparing"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CRASHED = "crashed"


class ReconstructionArtifactUpdate(BaseModel):
    """Artifact paths produced while a reconstruction workflow advances."""

    workspace_directory: str | None = None
    input_video_path: str | None = None
    raw_frames_directory: str | None = None
    frames_directory: str | None = None
    colmap_directory: str | None = None
    splat_path: str | None = None


class ReconstructionRead(BaseModel):
    """Reconstruction representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    building_id: UUID
    prefect_workflow_id: UUID | None
    status: ReconstructionStatus
    progress: float
    error_message: str | None
    settings: SplatGenerationWorkflowSettings
    workspace_directory: str | None
    input_video_path: str | None
    raw_frames_directory: str | None
    frames_directory: str | None
    colmap_directory: str | None
    splat_path: str | None
    created_at: datetime
    updated_at: datetime


class Reconstruction(SQLModel, table=True):  # type: ignore[call-arg]
    """A building reconstruction orchestrated by a Prefect flow run."""

    __tablename__ = "reconstructions"
    __table_args__ = (
        CheckConstraint(
            "progress BETWEEN 0 AND 1",
            name="ck_reconstructions_progress_range",
        ),
        CheckConstraint(
            "status IN ("
            "'preparing', 'scheduled', 'running', 'completed', "
            "'failed', 'cancelled', 'crashed'"
            ")",
            name="ck_reconstructions_status",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    building_id: UUID = Field(
        foreign_key="buildings.id",
        ondelete="CASCADE",
        index=True,
    )
    prefect_workflow_id: UUID | None = Field(default=None, index=True, unique=True)
    status: ReconstructionStatus = Field(
        default=ReconstructionStatus.PREPARING,
        sa_column=Column(String, nullable=False),
    )
    progress: float = Field(default=0.0, ge=0, le=1)
    error_message: str | None = None
    settings: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))

    workspace_directory: str | None = None
    input_video_path: str | None = None
    raw_frames_directory: str | None = None
    frames_directory: str | None = None
    colmap_directory: str | None = None
    splat_path: str | None = None

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    building: Building | None = Relationship(
        sa_relationship=relationship("Building", back_populates="reconstructions")
    )

    def apply_artifact_update_in_memory(
        self,
        update: ReconstructionArtifactUpdate,
    ) -> bool:
        """Apply explicitly supplied artifact paths without persisting the row."""

        changed = False
        for field_name, value in update.model_dump(exclude_unset=True).items():
            if getattr(self, field_name) != value:
                setattr(self, field_name, value)
                changed = True
        return changed

    def mark_scheduled_in_memory(self, prefect_workflow_id: UUID) -> None:
        """Record scheduling without moving a running row backwards."""

        self.prefect_workflow_id = prefect_workflow_id
        if self.status == ReconstructionStatus.PREPARING:
            self.status = ReconstructionStatus.SCHEDULED

    def mark_running_in_memory(self, prefect_workflow_id: UUID) -> bool:
        """Apply the running transition unless the row is already final."""

        if self.status in {
            ReconstructionStatus.COMPLETED,
            ReconstructionStatus.CANCELLED,
            ReconstructionStatus.CRASHED,
        }:
            return False

        self.prefect_workflow_id = prefect_workflow_id
        self.status = ReconstructionStatus.RUNNING
        self.progress = max(self.progress, 0.05)
        self.error_message = None
        return True

    def record_progress_in_memory(
        self,
        progress: float,
        artifact_update: ReconstructionArtifactUpdate | None = None,
    ) -> bool:
        """Advance progress and artifacts without persisting the row."""

        if not 0 <= progress <= 1:
            raise ValueError("progress must be between 0 and 1")
        if self.status in {
            ReconstructionStatus.COMPLETED,
            ReconstructionStatus.FAILED,
            ReconstructionStatus.CANCELLED,
            ReconstructionStatus.CRASHED,
        }:
            return False

        changed = False
        if progress > self.progress:
            self.progress = progress
            changed = True
        if artifact_update is not None:
            changed = self.apply_artifact_update_in_memory(artifact_update) or changed
        return changed

    def mark_completed_in_memory(
        self,
        artifacts: ReconstructionArtifactUpdate,
    ) -> None:
        """Apply successful completion and its final artifacts."""

        self.apply_artifact_update_in_memory(artifacts)
        self.status = ReconstructionStatus.COMPLETED
        self.progress = 1.0
        self.error_message = None

    def mark_terminal_in_memory(
        self,
        status: ReconstructionStatus,
        error_message: str | None,
    ) -> bool:
        """Apply a non-successful terminal state without persisting the row."""

        if status not in {
            ReconstructionStatus.FAILED,
            ReconstructionStatus.CANCELLED,
            ReconstructionStatus.CRASHED,
        }:
            raise ValueError("status must be failed, cancelled, or crashed")
        if self.status == ReconstructionStatus.COMPLETED:
            return False

        self.status = status
        self.error_message = error_message
        return True
