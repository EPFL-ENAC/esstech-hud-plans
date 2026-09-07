from __future__ import annotations

from uuid import UUID

from api.models.building import Building, BuildingCreate, BuildingUpdate
from api.models.user import utc_now
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession


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
    ) -> list[Building]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        result = await self._session.exec(
            select(Building)
            .where(Building.user_id == user_id)
            .order_by(col(Building.created_at), col(Building.id))
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

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
