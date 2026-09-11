from __future__ import annotations

import logging
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated
from uuid import UUID

from api.config import config
from api.lib.compute import scitas as scitas_compute
from api.lib.compute.colmap_geometric_data import colmap_compute_geometric_data
from api.lib.workflows import common as workflow_common
from api.lib.workflows.common import (
    WorkflowNotFoundError,
    cancel_workflow,
    current_workflow_step,
    get_owned_workflow_run,
    stream_workflow_logs,
)
from api.models.building import Building
from api.models.reconstruction import (
    Reconstruction,
    ReconstructionRead,
    ReconstructionStatus,
)
from api.services.reconstructions import (
    ReconstructionCreationError,
    ReconstructionNotFoundError,
    ReconstructionService,
    SortOrder,
)
from api.utils.responses import inline_file_response
from api.views.buildings import get_current_building
from api.views.reconstruction_submission import (
    get_reconstruction_service,
    validate_reconstruction_submission,
)
from fastapi import Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.routing import APIRouter
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

router = APIRouter()


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


CurrentReconstruction = Annotated[Reconstruction, Depends(get_current_reconstruction)]


@router.get("/{reconstruction_id}/video", response_class=FileResponse)
def get_reconstruction_video(
    reconstruction: CurrentReconstruction,
) -> FileResponse:
    if not reconstruction.input_video_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconstruction video not found",
        )

    path = Path(reconstruction.input_video_path)
    media_type = mimetypes.guess_type(path.name)[0]
    if media_type is None or not media_type.startswith("video/"):
        media_type = "application/octet-stream"

    return inline_file_response(
        path,
        root_directory=(
            workflow_common.WORKFLOW_DATA_DIRECTORY.resolve() / reconstruction.id.hex
        ),
        media_type=media_type,
    )


@router.get(
    "/{reconstruction_id}/blueprint-geometry",
    status_code=status.HTTP_200_OK,
)
def get_reconstruction_blueprint_geometry(
    reconstruction: CurrentReconstruction,
) -> JSONResponse:
    """Geometric info for the blueprint top-down view, computed from COLMAP output."""
    if (
        reconstruction.status != ReconstructionStatus.COMPLETED
        or not reconstruction.splat_path
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconstruction blueprint geometry not found",
        )

    sparse_dir = (
        workflow_common.WORKFLOW_DATA_DIRECTORY.resolve()
        / reconstruction.id.hex
        / "colmap"
        / "sparse"
        / "0"
    )
    if not sparse_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="COLMAP sparse reconstruction not found",
        )

    geometric_data = colmap_compute_geometric_data(str(sparse_dir))
    return JSONResponse(content=geometric_data.model_dump(mode="json"))


@router.get("/{reconstruction_id}/splat", response_class=FileResponse)
def get_reconstruction_splat(
    reconstruction: CurrentReconstruction,
) -> FileResponse:
    if (
        reconstruction.status != ReconstructionStatus.COMPLETED
        or not reconstruction.splat_path
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconstruction splat not found",
        )

    return inline_file_response(
        Path(reconstruction.splat_path),
        root_directory=(
            workflow_common.WORKFLOW_DATA_DIRECTORY.resolve() / reconstruction.id.hex
        ),
        media_type="application/octet-stream",
    )


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
    workflow_settings = validate_reconstruction_submission(file, settings)

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
    sort_order: SortOrder = "desc",
) -> list[Reconstruction]:
    try:
        return await reconstructions.list(
            building_id=building.id,
            offset=offset,
            limit=limit,
            sort_order=sort_order,
        )
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.get("/{reconstruction_id}", response_model=ReconstructionRead)
async def get_reconstruction(
    reconstruction: Annotated[Reconstruction, Depends(get_current_reconstruction)],
) -> Reconstruction:
    return reconstruction


@router.delete(
    "/{reconstruction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a reconstruction and its workflow data",
    description=(
        "Cancels the Prefect workflow if it is running, removes all workflow "
        "data from disk (video, frames, COLMAP output, splat), and deletes the "
        "reconstruction row. Prefect flow logs stay in the Prefect database."
    ),
)
async def delete_reconstruction(
    reconstruction: Annotated[Reconstruction, Depends(get_current_reconstruction)],
    reconstructions: Annotated[
        ReconstructionService,
        Depends(get_reconstruction_service),
    ],
) -> None:
    try:
        await reconstructions.delete(reconstruction)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.post(
    "/{reconstruction_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReconstructionRead,
)
async def cancel_reconstruction(
    reconstruction: Annotated[Reconstruction, Depends(get_current_reconstruction)],
    building: Annotated[Building, Depends(get_current_building)],
    reconstructions: Annotated[
        ReconstructionService,
        Depends(get_reconstruction_service),
    ],
) -> Reconstruction:
    if reconstruction.status not in (
        ReconstructionStatus.PREPARING,
        ReconstructionStatus.SCHEDULED,
        ReconstructionStatus.RUNNING,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Reconstruction is not processing (current status: {reconstruction.status})",
        )

    workflow_id = reconstruction.prefect_workflow_id
    if workflow_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reconstruction has no Prefect workflow",
        )

    try:
        await cancel_workflow(workflow_id)
    except WorkflowNotFoundError:
        # The workflow run no longer exists.
        pass

    # Cancel the related Slurm jobs now. The worker process does not notice
    # cancellation of tasks that are blocked on I/O, so it keeps their
    # Slurm jobs running.
    if config.USE_SCITAS:
        try:
            scitas_compute.cancel_registered_jobs(reconstruction.id.hex)
        except Exception:
            logger.exception(
                "Failed to cancel Slurm jobs for reconstruction %s", reconstruction.id
            )

    # The on_cancellation hook only runs in a worker or engine process that
    # observes the run, so mark the reconstruction as cancelled here.
    try:
        return await reconstructions.mark_cancelled(
            reconstruction.id,
            error_message="Cancellation requested",
        )
    except ReconstructionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconstruction not found",
        ) from exc
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.get("/{reconstruction_id}/current-step", response_model=str | None)
async def get_reconstruction_current_step(
    reconstruction: Annotated[Reconstruction, Depends(get_current_reconstruction)],
) -> str | None:
    if (
        reconstruction.status
        not in (
            ReconstructionStatus.PREPARING,
            ReconstructionStatus.SCHEDULED,
            ReconstructionStatus.RUNNING,
        )
        or reconstruction.prefect_workflow_id is None
    ):
        return None

    try:
        return await current_workflow_step(reconstruction.prefect_workflow_id)
    except Exception:
        logger.exception(
            "Failed to read current workflow step for reconstruction %s",
            reconstruction.id,
        )
        return None


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
