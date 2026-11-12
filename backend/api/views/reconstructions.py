from __future__ import annotations

import logging
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.routing import APIRouter
from sqlalchemy.exc import SQLAlchemyError

from api.config import config
from api.lib.compute.point_cloud import (
    POINT_CLOUD_BINARY_FILENAME,
    generate_plan_point_cloud_if_missing,
    read_point_cloud_meta,
)
from api.lib.workflows import common as workflow_common
from api.lib.workflows.common import (
    WorkflowNotFoundError,
    current_workflow_step,
    get_owned_workflow_run,
    stream_workflow_logs,
)
from api.lib.workflows.splat_generation import SplatGenerationArtifact
from api.models.building import Building
from api.models.pagination import Page
from api.models.reconstruction import (
    Reconstruction,
    ReconstructionRead,
    ReconstructionStatus,
)
from api.services.idempotency import IdempotencyInProgressError, IdempotencyService
from api.services.reconstructions import (
    ReconstructionConflictError,
    ReconstructionCreationError,
    ReconstructionInputNotFoundError,
    ReconstructionNotFoundError,
    ReconstructionService,
    SortOrder,
)
from api.utils.responses import file_storage_errors, inline_file_response
from api.views.buildings import get_current_building
from api.views.reconstruction_submission import (
    UploadReconstructionSubmission,
    get_idempotency_service,
    get_reconstruction_service,
)

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

    with file_storage_errors(config.DATA_PATH):
        return inline_file_response(
            path,
            root_directory=config.DATA_PATH.resolve() / "uploads",
            media_type=media_type,
        )


@router.get(
    "/{reconstruction_id}/view-params",
    status_code=status.HTTP_200_OK,
)
def get_reconstruction_view_params(
    reconstruction: CurrentReconstruction,
) -> JSONResponse:
    """Plan frame, scale and framing radius shared by both plan viewers.

    The 3D view applies ``matrix`` to the raw splat and the 2D view reads the
    baked point cloud, so both come from the single set of values stored next to
    the splat when it was baked.
    """
    if (
        reconstruction.status != ReconstructionStatus.COMPLETED
        or not reconstruction.splat_path
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconstruction view parameters not found",
        )

    artifact = SplatGenerationArtifact.from_local_reconstruction(reconstruction)
    if not artifact.colmap_sparse_directory.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="COLMAP sparse reconstruction not found",
        )

    with file_storage_errors(workflow_common.WORKFLOW_DATA_DIRECTORY):
        try:
            generate_plan_point_cloud_if_missing(
                artifact.splat_path,
                artifact.colmap_directory,
            )
        except Exception:
            logger.exception(
                "On-demand plan point cloud generation failed for reconstruction %s",
                reconstruction.id,
            )

        meta = read_point_cloud_meta(artifact.splat_path)

    if "matrix" not in meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconstruction view parameters not found",
        )

    return JSONResponse(content=meta)


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

    with file_storage_errors(workflow_common.WORKFLOW_DATA_DIRECTORY):
        artifact = SplatGenerationArtifact.from_local_reconstruction(reconstruction)
        return inline_file_response(
            artifact.splat_path,
            root_directory=artifact.root_directory,
            media_type="application/octet-stream",
        )


@router.get("/{reconstruction_id}/point-cloud", response_class=FileResponse)
def get_reconstruction_point_cloud(
    reconstruction: CurrentReconstruction,
) -> FileResponse:
    if (
        reconstruction.status != ReconstructionStatus.COMPLETED
        or not reconstruction.splat_path
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconstruction point cloud not found",
        )

    with file_storage_errors(workflow_common.WORKFLOW_DATA_DIRECTORY):
        artifact = SplatGenerationArtifact.from_local_reconstruction(reconstruction)
        try:
            generate_plan_point_cloud_if_missing(
                artifact.splat_path,
                artifact.colmap_directory,
            )
        except Exception:
            logger.exception(
                "On-demand plan point cloud generation failed for reconstruction %s",
                reconstruction.id,
            )

        return inline_file_response(
            artifact.root_directory / POINT_CLOUD_BINARY_FILENAME,
            root_directory=artifact.root_directory,
            media_type="application/octet-stream",
        )


@router.post(
    "/from-upload",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReconstructionRead,
    responses={
        204: {"description": "This operation was already accepted."},
        409: {
            "description": "The operation is being accepted or the upload has failed."
        },
    },
)
async def create_reconstruction_from_upload(
    payload: UploadReconstructionSubmission,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    building: Annotated[Building, Depends(get_current_building)],
    idempotency: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    reconstructions: Annotated[
        ReconstructionService,
        Depends(get_reconstruction_service),
    ],
) -> Reconstruction | Response:
    """Create a reconstruction from a pending or completed user upload."""

    try:
        async with idempotency.operation(
            owner_id=building.user_id,
            idempotency_key=idempotency_key,
        ) as should_run:
            if not should_run:
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            reconstruction = await reconstructions.add_from_upload(
                user_id=building.user_id,
                building_id=building.id,
                upload_id=payload.upload_id,
                settings=payload.settings,
            )
        return await reconstructions.schedule_if_ready(reconstruction.id)
    except IdempotencyInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "idempotency_in_progress"},
            headers={"Retry-After": "1"},
        ) from exc
    except ReconstructionInputNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ReconstructionConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
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


@router.get("", response_model=Page[ReconstructionRead])
async def list_reconstructions(
    building: Annotated[Building, Depends(get_current_building)],
    reconstructions: Annotated[
        ReconstructionService,
        Depends(get_reconstruction_service),
    ],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    sort_order: SortOrder = "desc",
) -> Page[Reconstruction]:
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
        await reconstructions.delete(reconstruction.id)
    except ReconstructionNotFoundError as exc:
        raise HTTPException(404, "Reconstruction not found") from exc
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.post(
    "/{reconstruction_id}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ReconstructionRead,
)
async def cancel_reconstruction(
    reconstruction: Annotated[Reconstruction, Depends(get_current_reconstruction)],
    reconstructions: Annotated[
        ReconstructionService,
        Depends(get_reconstruction_service),
    ],
) -> Reconstruction:
    try:
        return await reconstructions.cancel(reconstruction.id)
    except ReconstructionNotFoundError as exc:
        raise HTTPException(404, "Reconstruction not found") from exc
    except ReconstructionConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
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
