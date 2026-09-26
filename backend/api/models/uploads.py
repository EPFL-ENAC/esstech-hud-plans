from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from api.config import config
from api.models.user import utc_now
from api.models.workflows import SplatGenerationWorkflowSettings
from pydantic import BaseModel, model_validator
from pydantic import Field as PydanticField
from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    String,
)
from sqlmodel import Field, SQLModel


def _default_expires_at() -> datetime:
    return utc_now() + timedelta(hours=config.UPLOAD_SESSION_TTL_HOURS)


class UploadSessionStatus(StrEnum):
    UPLOADING = "uploading"
    FINALIZED = "finalized"


class ChunkPlanEntry(BaseModel):
    """One expected chunk of a chunked upload, declared by the client."""

    index: int = PydanticField(ge=0)
    size: int = PydanticField(gt=0)
    sha256: str = PydanticField(min_length=64, max_length=64, pattern=r"[0-9a-f]{64}")


class UploadSessionCreate(BaseModel):
    """Values accepted when creating a chunked upload session."""

    filename: str = PydanticField(min_length=1)
    total_size: int = PydanticField(gt=0)
    chunk_size: int = PydanticField(gt=0)
    settings: SplatGenerationWorkflowSettings = PydanticField(
        default_factory=SplatGenerationWorkflowSettings
    )
    building_id: UUID | None = None
    building: dict[str, object] | None = None
    chunks: list[ChunkPlanEntry]

    @model_validator(mode="after")
    def _require_exactly_one_building_input(self) -> UploadSessionCreate:
        if (self.building_id is None) == (self.building is None):
            raise ValueError("Provide exactly one of building_id or building")
        return self


class UploadSessionState(BaseModel):
    """Server state of one chunked upload session, returned to the client."""

    session_id: UUID
    status: UploadSessionStatus
    chunk_size: int
    total_chunks: int
    received_bytes: int
    expires_at: datetime
    missing_chunks: list[int]


class ChunkPutResult(BaseModel):
    """Result of storing one chunk."""

    received_bytes: int
    missing_chunks_count: int


class UploadSession(SQLModel, table=True):  # type: ignore[call-arg]
    """Server state of one chunked video upload."""

    __tablename__ = "upload_sessions"
    __table_args__ = (
        CheckConstraint("total_chunks >= 1", name="ck_upload_sessions_total_chunks"),
        CheckConstraint(
            "received_bytes <= total_size",
            name="ck_upload_sessions_received_bytes",
        ),
        CheckConstraint(
            "status IN ('uploading', 'finalized')",
            name="ck_upload_sessions_status",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        foreign_key="users.id",
        index=True,
    )
    building_id: UUID | None = Field(
        default=None,
        foreign_key="buildings.id",
        ondelete="CASCADE",
        index=True,
    )
    building_payload: dict[str, object] | None = Field(
        default=None,
        sa_column=Column(JSON),
    )
    settings: dict[str, object] = Field(sa_column=Column(JSON, nullable=False))
    status: UploadSessionStatus = Field(
        default=UploadSessionStatus.UPLOADING,
        sa_column=Column(String, nullable=False),
    )
    filename: str = Field(sa_column=Column(String, nullable=False))
    file_extension: str = Field(sa_column=Column(String, nullable=False), default="mp4")
    total_size: int = Field(sa_column=Column(BigInteger, nullable=False))
    chunk_size: int = Field(sa_column=Column(BigInteger, nullable=False))
    total_chunks: int = Field(sa_column=Column(BigInteger, nullable=False))
    received_bytes: int = Field(
        default=0,
        sa_column=Column(BigInteger, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    expires_at: datetime = Field(
        default_factory=_default_expires_at,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class UploadChunk(SQLModel, table=True):  # type: ignore[call-arg]
    """One expected chunk of an upload session and its received state."""

    __tablename__ = "upload_chunks"

    session_id: UUID = Field(
        foreign_key="upload_sessions.id",
        ondelete="CASCADE",
        primary_key=True,
    )
    chunk_index: int = Field(
        sa_column=Column(BigInteger, primary_key=True, nullable=False),
    )
    byte_offset: int = Field(sa_column=Column(BigInteger, nullable=False))
    expected_size: int = Field(sa_column=Column(BigInteger, nullable=False))
    expected_digest: str = Field(sa_column=Column(String(64), nullable=False))
    received_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True)),
    )
    received_digest: str | None = Field(
        default=None,
        sa_column=Column(String(64)),
    )
