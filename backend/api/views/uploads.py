from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from api.db import get_session
from api.models.uploads import (
    UserUploadRead,
    UserUploads,
    UserUploadUpdate,
)
from api.models.user import User
from api.services.auth import require_user
from api.services.uploads import SortOrder, UploadConflictError, UserUploadsService

logger = logging.getLogger(__name__)

router = APIRouter()


def get_uploads_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserUploadsService:
    """Build a request-scoped uploads service."""

    return UserUploadsService(session)


def _database_unavailable(exc: Exception) -> HTTPException:
    logger.exception("Upload database operation failed", exc_info=exc)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Upload database is unavailable",
    )


async def get_current_upload(
    upload_id: UUID,
    current_user: Annotated[User, Depends(require_user)],
    uploads: Annotated[UserUploadsService, Depends(get_uploads_service)],
) -> UserUploads:
    """Load an owned upload without revealing other users' rows."""

    try:
        upload = await uploads.get(upload_id, user_id=current_user.id)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc

    if upload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )
    return upload


@router.get("", response_model=list[UserUploadRead])
async def list_uploads(
    current_user: Annotated[User, Depends(require_user)],
    uploads: Annotated[UserUploadsService, Depends(get_uploads_service)],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    sort_order: SortOrder = "desc",
) -> list[UserUploads]:
    try:
        return await uploads.list(
            user_id=current_user.id,
            offset=offset,
            limit=limit,
            sort_order=sort_order,
        )
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.get("/{upload_id}", response_model=UserUploadRead)
async def get_upload(
    upload: Annotated[UserUploads, Depends(get_current_upload)],
) -> UserUploads:
    return upload


@router.patch("/{upload_id}", response_model=UserUploadRead)
async def update_upload(
    payload: UserUploadUpdate,
    upload: Annotated[UserUploads, Depends(get_current_upload)],
    uploads: Annotated[UserUploadsService, Depends(get_uploads_service)],
) -> UserUploads:
    try:
        return await uploads.update(upload, payload)
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_upload(
    upload: Annotated[UserUploads, Depends(get_current_upload)],
    uploads: Annotated[UserUploadsService, Depends(get_uploads_service)],
) -> None:
    """Delete the metadata row without touching files."""

    try:
        await uploads.delete(upload)
    except UploadConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (OSError, SQLAlchemyError) as exc:
        raise _database_unavailable(exc) from exc
