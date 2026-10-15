from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import BigInteger, Column, DateTime, String
from sqlmodel import Field, SQLModel

from api.models.user import utc_now


class UploadStatus(StrEnum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    FAILED = "failed"


class UserUploadCreate(BaseModel):
    """User-supplied metadata for a new upload."""

    model_config = ConfigDict(extra="forbid")

    name: str = "TODO"
    description: str = ""


class UserUploadUpdate(BaseModel):
    """Editable metadata, with omission representing no change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None

    @model_validator(mode="after")
    def validate_changes(self) -> UserUploadUpdate:
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class UserUploadRead(BaseModel):
    """Upload metadata returned by the API, excluding internal storage paths."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    description: str
    filename: str
    size_bytes: int
    status: UploadStatus
    created_at: datetime
    uploaded_at: datetime | None


class UserUploads(SQLModel, table=True):  # type: ignore[call-arg]
    """Metadata for a file upload owned by an application user."""

    __tablename__ = "user_uploads"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    name: str = "TODO"
    description: str = ""
    filename: str
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    file_path: str
    status: UploadStatus = Field(
        default=UploadStatus.PENDING,
        sa_column=Column(String, nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    uploaded_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
