from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from api.db import get_session
from api.models.building import Building, BuildingCreate, BuildingRead, BuildingUpdate
from api.models.user import User
from api.services.auth import require_user
from api.services.buildings import BuildingService
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter()


def get_building_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BuildingService:
    """Build a request-scoped building service."""

    return BuildingService(session)


def _database_unavailable(exc: Exception) -> HTTPException:
    logger.exception("Building database operation failed", exc_info=exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Building database is unavailable",
    )


async def get_current_building(
    building_id: UUID,
    current_user: Annotated[User, Depends(require_user)],
    buildings: Annotated[BuildingService, Depends(get_building_service)],
) -> Building:
    """Load a building owned by the current user without leaking other rows."""

    try:
        building = await buildings.get(building_id, user_id=current_user.id)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc

    if building is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Building not found",
        )
    return building


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=BuildingRead,
)
async def create_building(
    payload: BuildingCreate,
    current_user: Annotated[User, Depends(require_user)],
    buildings: Annotated[BuildingService, Depends(get_building_service)],
) -> Building:
    try:
        return await buildings.create(user_id=current_user.id, payload=payload)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.get("", response_model=list[BuildingRead])
async def list_buildings(
    current_user: Annotated[User, Depends(require_user)],
    buildings: Annotated[BuildingService, Depends(get_building_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[Building]:
    try:
        return await buildings.list(
            user_id=current_user.id,
            offset=offset,
            limit=limit,
        )
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.get("/{building_id}", response_model=BuildingRead)
async def get_building(
    building: Annotated[Building, Depends(get_current_building)],
) -> Building:
    return building


@router.patch("/{building_id}", response_model=BuildingRead)
async def update_building(
    payload: BuildingUpdate,
    building: Annotated[Building, Depends(get_current_building)],
    buildings: Annotated[BuildingService, Depends(get_building_service)],
) -> Building:
    try:
        return await buildings.update(building, payload)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.delete("/{building_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_building(
    building: Annotated[Building, Depends(get_current_building)],
    buildings: Annotated[BuildingService, Depends(get_building_service)],
) -> None:
    try:
        await buildings.delete(building)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc
