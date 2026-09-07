from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from pydantic import Field as PydanticField
from sqlalchemy import Column, DateTime
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from api.models.building import Building


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


class UserCreate(BaseModel):
    """Values accepted when creating a persisted user."""

    keycloak_sub: str = PydanticField(min_length=1)
    username: str | None = None
    email: str | None = None
    name: str | None = None


class UserUpdate(BaseModel):
    """Mutable persisted user fields."""

    username: str | None = None
    email: str | None = None
    name: str | None = None


class UserRead(BaseModel):
    """Persisted user representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str | None
    email: str | None
    name: str | None
    created_at: datetime
    updated_at: datetime


class User(SQLModel, table=True):  # type: ignore[call-arg]
    """Application user associated with a Keycloak identity."""

    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    keycloak_sub: str = Field(index=True, unique=True)
    username: str | None = Field(default=None, index=True)
    email: str | None = Field(default=None, index=True)
    name: str | None = None
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    buildings: list[Building] = Relationship(
        sa_relationship=relationship(
            "Building",
            back_populates="user",
            cascade="all, delete-orphan",
            passive_deletes=True,
        )
    )
