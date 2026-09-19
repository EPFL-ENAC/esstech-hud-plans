"""Shared dependencies and validation for video reconstruction submissions."""

import mimetypes
from typing import Annotated

from api.db import get_session
from api.models.workflows import SplatGenerationWorkflowSettings
from api.services.reconstructions import ReconstructionService
from fastapi import Depends, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession


def get_reconstruction_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReconstructionService:
    """Build a request-scoped reconstruction service."""

    return ReconstructionService(session)


def validate_reconstruction_submission(
    video: UploadFile,
    settings: str,
) -> SplatGenerationWorkflowSettings:
    """Validate a video upload and decode the workflow settings.

    Client-provided content types are not trusted. Browsers can send an empty
    or generic type when they cannot detect the MIME type of the selected file.
    """
    if not video.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must have a filename",
        )
    media_type = mimetypes.guess_type(video.filename)[0]
    if media_type is None or not media_type.startswith("video/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a video",
        )

    try:
        return SplatGenerationWorkflowSettings.model_validate_json(settings)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(include_url=False),
        ) from exc
