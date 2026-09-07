from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from api.models.user import utc_now
from pydantic import BaseModel, ConfigDict, model_validator
from pydantic import Field as PydanticField
from sqlalchemy import CheckConstraint, Column, DateTime
from sqlalchemy.orm import relationship
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from api.models.user import User


class BuildingCreate(BaseModel):
    """Values accepted when creating a building."""

    name: str = PydanticField(min_length=1)
    latitude: float = PydanticField(ge=-90, le=90)
    longitude: float = PydanticField(ge=-180, le=180)


class BuildingUpdate(BaseModel):
    """Mutable building fields, with omission representing no change."""

    name: str | None = PydanticField(default=None, min_length=1)
    latitude: float | None = PydanticField(default=None, ge=-90, le=90)
    longitude: float | None = PydanticField(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> BuildingUpdate:
        for field_name in self.model_fields_set:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class BuildingRead(BaseModel):
    """Building representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    latitude: float
    longitude: float
    created_at: datetime
    updated_at: datetime


class Building(SQLModel, table=True):  # type: ignore[call-arg]
    """A named geographic location owned by an application user."""

    __tablename__ = "buildings"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_buildings_name_nonempty"),
        CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_buildings_latitude_range",
        ),
        CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_buildings_longitude_range",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    name: str
    latitude: float
    longitude: float
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    user: User | None = Relationship(
        sa_relationship=relationship("User", back_populates="buildings")
    )
