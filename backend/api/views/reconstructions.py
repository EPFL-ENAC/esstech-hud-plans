from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from api.db import get_session
from api.lib.workflows.common import (
    WorkflowNotFoundError,
    get_owned_workflow_run,
    stream_workflow_logs,
)
from api.models.building import Building
from api.models.reconstruction import Reconstruction, ReconstructionRead
from api.models.workflows import SplatGenerationWorkflowSettings
from api.services.reconstructions import (
    ReconstructionCreationError,
    ReconstructionService,
)
from api.views.buildings import get_current_building
from fastapi import Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRouter
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter()


def get_reconstruction_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReconstructionService:
    """Build a request-scoped reconstruction service."""

    return ReconstructionService(session)


def _database_unavailable(exc: Exception) -> HTTPException:
    logger.exception("Reconstruction database operation failed", exc_info=exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Reconstruction database is unavailable",
    )


async def get_current_reconstruction(
    reconstruction_id: UUID,
    building: Annotated[Building, Depends(get_current_building)],
    reconstructions: Annotated[
        ReconstructionService,
        Depends(get_reconstruction_service),
    ],
) -> Reconstruction:
    """Load a reconstruction through its already-authorized parent building."""

    try:
        reconstruction = await reconstructions.get(
            reconstruction_id,
            building_id=building.id,
        )
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc

    if reconstruction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconstruction not found",
        )
    return reconstruction


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReconstructionRead,
)
async def create_reconstruction(
    file: Annotated[UploadFile, File()],
    settings: Annotated[str, Form(...)],
    building: Annotated[Building, Depends(get_current_building)],
    reconstructions: Annotated[
        ReconstructionService,
        Depends(get_reconstruction_service),
    ],
) -> Reconstruction:
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must have a filename",
        )
    if file.content_type is None or not file.content_type.startswith("video/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a video",
        )

    try:
        workflow_settings = SplatGenerationWorkflowSettings.model_validate_json(
            settings
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(include_url=False),
        ) from exc

    try:
        return await reconstructions.create_from_video(
            building=building,
            video=file,
            settings=workflow_settings,
        )
    except ReconstructionCreationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": str(exc),
                "reconstruction_id": str(exc.reconstruction.id),
            },
        ) from exc
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.get("", response_model=list[ReconstructionRead])
async def list_reconstructions(
    building: Annotated[Building, Depends(get_current_building)],
    reconstructions: Annotated[
        ReconstructionService,
        Depends(get_reconstruction_service),
    ],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> list[Reconstruction]:
    try:
        return await reconstructions.list(
            building_id=building.id,
            offset=offset,
            limit=limit,
        )
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.get("/{reconstruction_id}", response_model=ReconstructionRead)
async def get_reconstruction(
    reconstruction: Annotated[Reconstruction, Depends(get_current_reconstruction)],
) -> Reconstruction:
    return reconstruction


@router.get("/{reconstruction_id}/logs", response_class=StreamingResponse)
async def listen_to_reconstruction(
    reconstruction: Annotated[Reconstruction, Depends(get_current_reconstruction)],
    building: Annotated[Building, Depends(get_current_building)],
) -> StreamingResponse:
    workflow_id = reconstruction.prefect_workflow_id
    if workflow_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reconstruction has no Prefect workflow",
        )

    try:
        flow_run = await get_owned_workflow_run(workflow_id, building.user_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconstruction workflow not found",
        ) from exc
    except Exception as exc:
        logger.exception("Failed to load reconstruction workflow")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow service is unavailable",
        ) from exc

    workflow_stream = stream_workflow_logs(flow_run)
    try:
        first_item = await anext(workflow_stream)
    except Exception as exc:
        await workflow_stream.aclose()
        logger.exception("Failed to start reconstruction workflow log stream")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow log stream is unavailable",
        ) from exc

    async def event_stream() -> AsyncIterator[str]:
        try:
            yield first_item.to_sse_event()
            async for item in workflow_stream:
                yield item.to_sse_event()
        finally:
            await workflow_stream.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
