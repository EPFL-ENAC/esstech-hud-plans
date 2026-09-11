from __future__ import annotations

import builtins
from typing import Literal
from uuid import UUID

from api.models.building import (
    Building,
    BuildingCreate,
    BuildingListItemRead,
    BuildingLocationRead,
    BuildingRead,
    BuildingUpdate,
)
from api.models.reconstruction import Reconstruction, ReconstructionStatus
from api.models.user import utc_now
from api.services.reconstructions import ReconstructionService
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

SortOrder = Literal["asc", "desc"]
ReconstructionStatusFilter = Literal["processing", "idle"]

ACTIVE_RECONSTRUCTION_STATUSES = (
    ReconstructionStatus.PREPARING,
    ReconstructionStatus.SCHEDULED,
    ReconstructionStatus.RUNNING,
)


class BuildingService:
    """Create, query, update, and delete user-owned building rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, building_id: UUID, *, user_id: UUID) -> Building | None:
        result = await self._session.exec(
            select(Building).where(
                Building.id == building_id,
                Building.user_id == user_id,
            )
        )
        return result.first()

    async def list(
        self,
        *,
        user_id: UUID,
        offset: int = 0,
        limit: int = 100,
        sort_order: SortOrder = "desc",
        reconstruction_status: ReconstructionStatusFilter | None = None,
        search: str | None = None,
    ) -> builtins.list[BuildingListItemRead]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if sort_order not in ("asc", "desc"):
            raise ValueError("sort_order must be asc or desc")
        if reconstruction_status not in (None, "processing", "idle"):
            raise ValueError("reconstruction_status must be processing or idle")

        ordering = (
            (col(Building.created_at).asc(), col(Building.id).asc())
            if sort_order == "asc"
            else (col(Building.created_at).desc(), col(Building.id).desc())
        )

        latest_reconstruction_id = (
            select(Reconstruction.id)
            .where(Reconstruction.building_id == Building.id)
            .order_by(
                col(Reconstruction.created_at).desc(), col(Reconstruction.id).desc()
            )
            .limit(1)
            .correlate(Building)
            .scalar_subquery()
        )
        statement = (
            select(Building, Reconstruction)
            .outerjoin(Reconstruction, Reconstruction.id == latest_reconstruction_id)
            .where(Building.user_id == user_id)
        )
        if reconstruction_status is not None:
            # Check every attempt, independently of the latest-attempt summary.
            active_attempt_exists = (
                select(Reconstruction.id)
                .where(
                    Reconstruction.building_id == Building.id,
                    col(Reconstruction.status).in_(ACTIVE_RECONSTRUCTION_STATUSES),
                )
                .correlate(Building)
                .exists()
            )
            statement = statement.where(
                active_attempt_exists
                if reconstruction_status == "processing"
                else ~active_attempt_exists
            )

        term = (search or "").strip()
        if term:
            statement = statement.where(
                col(Building.name).icontains(term, autoescape=True)
            )

        result = await self._session.exec(
            statement.order_by(*ordering).offset(offset).limit(limit)
        )
        return [
            BuildingRead.model_validate(building).to_list_item(reconstruction)
            for building, reconstruction in result.all()
        ]

    async def list_locations(
        self, *, user_id: UUID
    ) -> builtins.list[BuildingLocationRead]:
        result = await self._session.exec(
            select(Building.id, Building.name, Building.latitude, Building.longitude)
            .where(
                Building.user_id == user_id,
                col(Building.latitude).is_not(None),
                col(Building.longitude).is_not(None),
            )
            .order_by(col(Building.id))
        )
        return [
            BuildingLocationRead.model_validate(row._mapping) for row in result.all()
        ]

    async def create(
        self,
        *,
        user_id: UUID,
        payload: BuildingCreate,
    ) -> Building:
        building = Building(user_id=user_id, **payload.model_dump())
        self._session.add(building)
        await self._commit_and_refresh(building)
        return building

    async def update(
        self,
        building: Building,
        payload: BuildingUpdate,
    ) -> Building:
        changes = payload.model_dump(exclude_unset=True)
        changed = any(
            getattr(building, field_name) != value
            for field_name, value in changes.items()
        )
        if not changed:
            return building

        for field_name, value in changes.items():
            setattr(building, field_name, value)

        building.updated_at = utc_now()
        self._session.add(building)
        await self._commit_and_refresh(building)
        return building

    async def delete(self, building: Building) -> None:
        # Reconstruct rows cascade-delete with the building, but their workflow
        # runs and artifact files must be cleaned up first to avoid leaks.
        result = await self._session.exec(
            select(Reconstruction).where(Reconstruction.building_id == building.id)
        )
        reconstruction_service = ReconstructionService(self._session)
        for reconstruction in result.all():
            await reconstruction_service.delete(reconstruction)

        try:
            await self._session.delete(building)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def _commit_and_refresh(self, building: Building) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(building)
