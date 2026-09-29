"""Shared dependencies and validation for resumable video reconstruction submissions."""

import json
import mimetypes
import re
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from api.config import config
from api.db import get_session
from api.models.building import BuildingCreate
from api.models.workflows import SplatGenerationWorkflowSettings
from api.services.reconstructions import ReconstructionService

# tusd upload ids are hex tokens; keep the whitelist tight so an id can never
# escape TUSD_UPLOAD_DIR.
TUS_UPLOAD_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def get_reconstruction_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReconstructionService:
    """Build a request-scoped reconstruction service."""

    return ReconstructionService(session)


def validate_video_filename(filename: str | None) -> str:
    """Check that an upload metadata filename resolves to a video."""

    if not isinstance(filename, str) or not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload metadata must contain a filename",
        )
    media_type = mimetypes.guess_type(filename)[0]
    if media_type is None or not media_type.startswith("video/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a video",
        )
    return filename


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


def validate_tus_upload(upload_id: str) -> tuple[Path, str]:
    """Validate a completed tus upload and return its path and filename.

    tusd stores "<id>" (binary) and "<id>.info" (JSON) under TUSD_UPLOAD_DIR.
    The .info Offset field is stale while chunks stream in; the binary file
    size is the authoritative completeness signal.
    """

    if not TUS_UPLOAD_ID_PATTERN.fullmatch(upload_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload id",
        )

    upload_dir = Path(config.TUSD_UPLOAD_DIR)
    binary_path = upload_dir / upload_id
    info_path = upload_dir / f"{upload_id}.info"

    try:
        binary_size = binary_path.stat().st_size
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload not found or empty",
        ) from exc
    if not binary_path.is_file() or binary_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload not found or empty",
        )

    try:
        info = json.loads(info_path.read_text())
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload state is unreadable",
        ) from exc
    if not isinstance(info, dict) or info.get("SizeIsDeferred"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload size is unknown",
        )
    size = info.get("Size")
    metadata = info.get("MetaData") or {}
    filename = metadata.get("filename") if isinstance(metadata, dict) else None
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
        or binary_size != size
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload is not complete",
        )

    return binary_path, validate_video_filename(filename)
