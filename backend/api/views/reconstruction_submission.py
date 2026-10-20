"""Shared dependencies and validation for video reconstruction submissions."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

from api.db import get_session
from api.lib.tus import parse_upload_id
from api.models.building import BuildingCreate
from api.models.uploads import UploadStatus, UserUploads
from api.models.workflows import SplatGenerationWorkflowSettings
from api.services.reconstructions import ReconstructionService
from api.services.uploads import (
    UploadConflictError,
    UploadNotFoundError,
    UserUploadsService,
)

logger = logging.getLogger(__name__)


def get_reconstruction_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReconstructionService:
    """Build a request-scoped reconstruction service."""

    return ReconstructionService(session)


class ResumableReconstructionSubmission(BaseModel):
    """Body for resumable (tus) reconstruction submissions."""

    tus_upload_id: str
    settings: SplatGenerationWorkflowSettings = Field(
        default_factory=SplatGenerationWorkflowSettings
    )


class ResumableBuildingFromReconstructionSubmission(BaseModel):
    """Body for resumable (tus) building-plus-reconstruction submissions."""

    tus_upload_id: str
    building: BuildingCreate = Field(default_factory=BuildingCreate)
    settings: SplatGenerationWorkflowSettings = Field(
        default_factory=SplatGenerationWorkflowSettings
    )


class UploadReconstructionSubmission(BaseModel):
    """Submit a pending or completed user upload."""

    upload_id: UUID
    settings: SplatGenerationWorkflowSettings = Field(
        default_factory=SplatGenerationWorkflowSettings
    )


class BuildingFromUploadReconstructionSubmission(UploadReconstructionSubmission):
    building: BuildingCreate = Field(default_factory=BuildingCreate)


async def validate_user_upload(
    upload_id: UUID,
    *,
    user_id: UUID,
    uploads: UserUploadsService,
) -> UserUploads:
    """Resolve an owned pending or completed upload before creating rows."""

    try:
        upload = await uploads.get(upload_id, user_id=user_id)
        if upload is None:
            raise UploadNotFoundError("Upload not found")
        if upload.status == UploadStatus.PENDING:
            return upload
        return await uploads.get_completed(upload_id, user_id=user_id)
    except UploadNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except UploadConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except (OSError, SQLAlchemyError) as exc:
        logger.exception("Reconstruction upload is unavailable")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Upload persistence is unavailable",
        ) from exc


async def validate_tus_upload(
    upload_id: str,
    *,
    user_id: UUID,
    uploads: UserUploadsService,
) -> UserUploads:
    """Resolve a pending or completed tus upload belonging to the user."""

    parsed_id = parse_upload_id(upload_id)
    return await validate_user_upload(parsed_id, user_id=user_id, uploads=uploads)
