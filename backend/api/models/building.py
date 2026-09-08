from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from api.models.reconstruction import Reconstruction, ReconstructionSummary
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

    name: str = ""
    latitude: float | None = PydanticField(default=None, ge=-90, le=90)
    longitude: float | None = PydanticField(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_coordinate_pair(self) -> BuildingCreate:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must both be set or both be null")
        return self


class BuildingUpdate(BaseModel):
    """Mutable building fields, with omission representing no change."""

    name: str | None = None
    latitude: float | None = PydanticField(default=None, ge=-90, le=90)
    longitude: float | None = PydanticField(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_changes(self) -> BuildingUpdate:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")

        coordinate_fields = {"latitude", "longitude"}
        provided_coordinates = self.model_fields_set & coordinate_fields
        if provided_coordinates and provided_coordinates != coordinate_fields:
            raise ValueError("latitude and longitude must be updated together")
        if provided_coordinates and (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must both be set or both be null")
        return self


class BuildingRead(BaseModel):
    """Building representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    latitude: float | None
    longitude: float | None
    created_at: datetime
    updated_at: datetime

    def to_list_item(
        self,
        reconstruction: Reconstruction | None,
    ) -> BuildingListItemRead:
        return BuildingListItemRead(
            **self.model_dump(),
            latest_reconstruction=(
                ReconstructionSummary.from_reconstruction(reconstruction)
                if reconstruction is not None
                else None
            ),
        )


class BuildingLocationRead(BaseModel):
    """The fields needed to place an owned building on a map."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    latitude: float
    longitude: float


class BuildingListItemRead(BuildingRead):
    """A building with its newest attempt, regardless of that attempt's status."""

    latest_reconstruction: ReconstructionSummary | None


class Building(SQLModel, table=True):  # type: ignore[call-arg]
    """A named geographic location owned by an application user."""

    __tablename__ = "buildings"
    __table_args__ = (
        CheckConstraint(
            "latitude BETWEEN -90 AND 90",
            name="ck_buildings_latitude_range",
        ),
        CheckConstraint(
            "longitude BETWEEN -180 AND 180",
            name="ck_buildings_longitude_range",
        ),
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude IS NOT NULL AND longitude IS NOT NULL)",
            name="ck_buildings_coordinates_complete",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(
        foreign_key="users.id",
        ondelete="CASCADE",
        index=True,
    )
    name: str
    latitude: float | None = None
    longitude: float | None = None
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
    reconstructions: list[Reconstruction] = Relationship(
        sa_relationship=relationship(
            "Reconstruction",
            back_populates="building",
            cascade="all, delete-orphan",
            passive_deletes=True,
        )
    )
