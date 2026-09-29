from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from api.db import get_session
from api.models.building import (
    Building,
    BuildingCreate,
    BuildingFromReconstructionError,
    BuildingFromReconstructionRead,
    BuildingListItemRead,
    BuildingLocationRead,
    BuildingRead,
    BuildingUpdate,
)
from api.models.reconstruction import ReconstructionRead
from api.models.user import User
from api.services.auth import require_user
from api.services.buildings import (
    BuildingService,
    ReconstructionStatusFilter,
    SortOrder,
)
from api.services.reconstructions import (
    ReconstructionCreationError,
    ReconstructionService,
)
from api.views.reconstruction_submission import (
    ResumableBuildingFromReconstructionSubmission,
    get_reconstruction_service,
    validate_tus_upload,
)

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


@router.post(
    "/from-reconstruction/resumable",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BuildingFromReconstructionRead,
    responses={
        400: {"description": "The tus upload is missing, incomplete, or not a video."},
        401: {"description": "Authentication is required."},
        422: {"description": "Missing fields or invalid building/workflow settings."},
        503: {
            "model": BuildingFromReconstructionError,
            "description": (
                "Database or scheduling failure. Once created, the "
                "building is retained and building_id is returned. A persisted "
                "failed reconstruction is also retained and its ID is included."
            ),
        },
    },
)
async def create_building_from_reconstruction_resumable(
    payload: ResumableBuildingFromReconstructionSubmission,
    current_user: Annotated[User, Depends(require_user)],
    buildings: Annotated[BuildingService, Depends(get_building_service)],
    reconstructions: Annotated[
        ReconstructionService, Depends(get_reconstruction_service)
    ],
) -> BuildingFromReconstructionRead:
    """Create an owned building, then submit its first reconstruction from a
    completed tus upload."""
    tus_upload_path, tus_video_filename = validate_tus_upload(payload.tus_upload_id)

    try:
        created_building = await buildings.create(
            user_id=current_user.id, payload=payload.building
        )
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc

    # Keep response data available even if reconstruction rollback expires ORM rows.
    building_read = BuildingRead.model_validate(created_building)
    try:
        reconstruction = await reconstructions.create_from_tus(
            building=created_building,
            tus_upload_path=str(tus_upload_path),
            tus_video_filename=tus_video_filename,
            settings=payload.settings,
        )
    except ReconstructionCreationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": str(exc),
                "building_id": str(building_read.id),
                "reconstruction_id": str(exc.reconstruction.id),
            },
        ) from exc
    except (OSError, SQLAlchemyError) as exc:
        logger.exception("Reconstruction database operation failed", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Reconstruction database is unavailable",
                "building_id": str(building_read.id),
            },
        ) from exc

    return BuildingFromReconstructionRead(
        building=building_read,
        reconstruction=ReconstructionRead.model_validate(reconstruction),
    )


@router.get("", response_model=list[BuildingListItemRead])
async def list_buildings(
    current_user: Annotated[User, Depends(require_user)],
    buildings: Annotated[BuildingService, Depends(get_building_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    sort_order: SortOrder = "desc",
    reconstruction_status: Annotated[
        ReconstructionStatusFilter | None,
        Query(
            description="Filter by whether any attempt is preparing, scheduled, or running."
        ),
    ] = None,
    search: Annotated[
        str | None,
        Query(
            description="Case-insensitive substring of the building name; blank means all names."
        ),
    ] = None,
) -> list[BuildingListItemRead]:
    try:
        return await buildings.list(
            user_id=current_user.id,
            offset=offset,
            limit=limit,
            sort_order=sort_order,
            reconstruction_status=reconstruction_status,
            search=search,
        )
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.get("/locations", response_model=list[BuildingLocationRead])
async def list_building_locations(
    current_user: Annotated[User, Depends(require_user)],
    buildings: Annotated[BuildingService, Depends(get_building_service)],
) -> list[BuildingLocationRead]:
    try:
        return await buildings.list_locations(user_id=current_user.id)
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
