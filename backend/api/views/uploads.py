"""HTTP endpoints for chunked video upload sessions."""

import hashlib
import logging
import os
from typing import Annotated, Union
from uuid import UUID, uuid4

from api.db import get_session
from api.lib.uploads import paths
from api.models.building import BuildingFromReconstructionRead
from api.models.reconstruction import ReconstructionRead
from api.models.uploads import (
    ChunkPutResult,
    UploadSessionCreate,
    UploadSessionState,
    UploadSessionStatus,
)
from api.models.user import User
from api.services.auth import require_user
from api.services.buildings import BuildingService
from api.services.uploads import (
    FinalizeResponse,
    UploadAssemblyError,
    UploadChunkNotFoundError,
    UploadFinalizationError,
    UploadService,
    UploadSessionExpiredError,
    UploadSessionFinalizedError,
    UploadSessionNotCompleteError,
    UploadSessionNotFoundError,
)
from api.views.buildings import get_building_service
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


class _ChunkBodyTooLargeError(Exception):
    """Raised when a streamed chunk body overshoots the planned size."""


router = APIRouter(dependencies=[Depends(require_user)])


def get_upload_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UploadService:
    """Build a request-scoped upload service."""

    return UploadService(session)


def get_current_user(
    current_user: Annotated[User, Depends(require_user)],
) -> User:
    """Expose the router-authenticated user to the endpoint handlers."""

    return current_user


async def _owned_session(
    uploads: UploadService,
    session_id: UUID,
    user_id: UUID,
):
    """Load an owned session, rejecting foreign, missing, or expired rows."""

    try:
        session_row = await uploads.get_owned_session(session_id, user_id=user_id)
    except UploadSessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found",
        )
    try:
        uploads.assert_not_expired(session_row)
    except UploadSessionExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Upload session expired",
        )
    return session_row


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=UploadSessionState,
    summary="Create a chunked upload session",
)
async def create_upload_session(
    payload: UploadSessionCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    uploads: Annotated[UploadService, Depends(get_upload_service)],
    buildings: Annotated[BuildingService, Depends(get_building_service)],
) -> UploadSessionState:
    """Validate the upload and create the session with its chunk rows."""

    session_row = None
    building = None
    if payload.building_id is not None:
        building = await buildings.get(payload.building_id, user_id=current_user.id)
        if building is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Building not found",
            )

    try:
        session_row = await uploads.create_session(
            user_id=current_user.id,
            payload=payload,
            building=building,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except (OSError, SQLAlchemyError) as exc:
        logger.exception("Failed to create upload session")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload database is unavailable",
        ) from exc

    return await uploads.state_for(session_row)


@router.put(
    "/{session_id}/chunks/{chunk_index}",
    status_code=status.HTTP_200_OK,
    response_model=ChunkPutResult,
    summary="Store one chunk of a chunked upload",
)
async def put_chunk(
    request: Request,
    session_id: UUID,
    chunk_index: int,
    current_user: Annotated[User, Depends(get_current_user)],
    uploads: Annotated[UploadService, Depends(get_upload_service)],
) -> ChunkPutResult:
    """Stream a raw chunk body to a part file and record it atomically."""

    session_row = await _owned_session(uploads, session_id, current_user.id)
    if session_row.status == UploadSessionStatus.FINALIZED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload session is already finalized",
        )

    try:
        chunk = await uploads.get_chunk(session_id, chunk_index)
    except UploadChunkNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chunk not found",
        )

    missing = await uploads.missing_chunks(session_id)
    if chunk.received_at is not None:
        # Already stored chunks stay accepted so retries stay idempotent.
        return ChunkPutResult(
            received_bytes=session_row.received_bytes,
            missing_chunks_count=len(missing),
        )

    paths.make_session_temp_dir(session_id)
    part = paths.part_file(session_id, chunk_index)
    # A unique per-request part name keeps concurrent duplicate PUTs from
    # interleaving into one shared file.
    clone = part.with_name(f"{part.name}.{uuid4().hex[:12]}.tmp")
    hasher = hashlib.sha256()
    total = 0
    try:
        with clone.open("wb") as destination:
            async for piece in request.stream():
                # Hashing and writes are blocking: keep them off the loop.
                await run_in_threadpool(hasher.update, piece)
                await run_in_threadpool(destination.write, piece)
                total += len(piece)
                if total > chunk.expected_size:
                    raise _ChunkBodyTooLargeError
    except _ChunkBodyTooLargeError:
        await _discard(clone, part)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chunk size does not match the upload plan",
        ) from None
    except OSError as exc:
        logger.exception(
            "Failed to stream chunk %s of session %s", chunk_index, session_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chunk storage is unavailable",
        ) from exc

    if total != chunk.expected_size:
        await _discard(clone, part)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chunk size does not match the upload plan",
        )
    digest = hasher.hexdigest()
    if digest != chunk.expected_digest:
        await _discard(clone, part)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chunk digest does not match the upload plan",
        )

    await run_in_threadpool(os.replace, clone, part)

    try:
        return await uploads.record_chunk(session_id, chunk_index, digest=digest)
    except (OSError, SQLAlchemyError) as exc:
        logger.exception(
            "Failed to record chunk %s of session %s", chunk_index, session_id
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload database is unavailable",
        ) from exc


async def _discard(clone: os.PathLike[str], part: os.PathLike[str]) -> None:
    """Remove a rejected chunk part and its temporary clone."""

    await run_in_threadpool(_unlink, clone, part)


def _unlink(*paths_: os.PathLike[str]) -> None:
    for path in paths_:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


@router.get(
    "/{session_id}",
    status_code=status.HTTP_200_OK,
    response_model=UploadSessionState,
    summary="Return the state of a chunked upload session",
)
async def get_upload_session(
    session_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    uploads: Annotated[UploadService, Depends(get_upload_service)],
) -> UploadSessionState:
    session_row = await _owned_session(uploads, session_id, current_user.id)
    return await uploads.state_for(session_row)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a chunked upload session",
)
async def delete_upload_session(
    session_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    uploads: Annotated[UploadService, Depends(get_upload_service)],
) -> None:
    session_row = await _owned_session(uploads, session_id, current_user.id)
    await uploads.delete_session(session_row)


@router.post(
    "/{session_id}/finalize",
    status_code=status.HTTP_200_OK,
    response_model=Union[ReconstructionRead, BuildingFromReconstructionRead],
    summary="Finalize a chunked upload and submit its reconstruction",
)
async def finalize_upload(
    session_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    uploads: Annotated[UploadService, Depends(get_upload_service)],
) -> FinalizeResponse:
    """Assemble, copy to the target directory, submit, and clean the session."""

    try:
        return await uploads.finalize(session_id, user_id=current_user.id)
    except UploadSessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found",
        )
    except UploadSessionExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Upload session expired",
        )
    except UploadSessionFinalizedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload session is already finalized",
        )
    except UploadSessionNotCompleteError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Upload session is not complete",
                "missing_chunks": exc.missing_chunks,
            },
        )
    except UploadAssemblyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    except UploadFinalizationError as exc:
        detail: dict[str, object] = {
            "message": str(exc),
            "reconstruction_id": str(exc.reconstruction_id),
        }
        if exc.building_id is not None:
            detail["building_id"] = str(exc.building_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )
    except (OSError, SQLAlchemyError) as exc:
        logger.exception("Upload finalization failed", exc_info=exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reconstruction database is unavailable",
        )
