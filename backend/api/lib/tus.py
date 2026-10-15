"""Translate tusd events and identifiers into application upload metadata."""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status

from api.config import config

TUS_UPLOAD_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
TUS_UPLOAD_ID_HEADER = "X-HUD-Upload-ID"
TUS_HOOK_SECRET_HEADER = "X-HUD-Tus-Hook-Secret"
TUS_COMPLETION_TIMEOUT_SECONDS = 30 * 60


@dataclass(frozen=True)
class TusUploadEvent:
    upload_id: UUID
    filename: str
    size_bytes: int
    offset: int
    bearer_token: str | None

    @classmethod
    def from_hooks_payload(
        cls,
        payload: dict[str, Any],
    ) -> TusUploadEvent:
        """Validate and normalize a tusd hook payload."""

        event = payload.get("Event")
        if not isinstance(event, dict):
            raise HTTPException(400, "Invalid hook event")
        upload = event.get("Upload")
        if not isinstance(upload, dict):
            raise HTTPException(400, "Invalid hook upload")
        http_request = event.get("HTTPRequest")
        if not isinstance(http_request, dict):
            raise HTTPException(400, "Invalid hook request")
        headers = http_request.get("Header") or {}
        if not isinstance(headers, dict):
            raise HTTPException(400, "Invalid hook headers")

        token = next(
            (
                value[len("bearer ") :].strip()
                for value in _header_values(headers, "Authorization")
                if value.lower().startswith("bearer ")
            ),
            None,
        )
        if payload.get("Type") == "pre-create":
            if not token:
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    "Missing bearer token",
                )
            ids = _header_values(headers, TUS_UPLOAD_ID_HEADER)
            raw_id = ids[0] if len(ids) == 1 else None
        else:
            raw_id = upload.get("ID")
        if not isinstance(raw_id, str):
            raise HTTPException(400, "Invalid upload id")

        metadata = upload.get("MetaData") or {}
        filename = validate_video_filename(
            metadata.get("filename") if isinstance(metadata, dict) else None
        )
        size = upload.get("Size")
        if (
            upload.get("SizeIsDeferred")
            or not isinstance(size, int)
            or isinstance(size, bool)
            or not 0 < size <= 2**63 - 1
        ):
            raise HTTPException(400, "Upload size must be known and positive")
        offset = upload.get("Offset")
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or not 0 <= offset <= size
        ):
            raise HTTPException(400, "Invalid upload offset")
        if (
            upload.get("IsPartial")
            or upload.get("IsFinal")
            or upload.get("PartialUploads")
        ):
            raise HTTPException(400, "Concatenated uploads are not supported")

        return cls(
            upload_id=parse_upload_id(raw_id),
            filename=filename,
            size_bytes=size,
            offset=offset,
            bearer_token=token,
        )


def validate_video_filename(filename: str | None) -> str:
    """Check that upload metadata identifies a video."""

    if not isinstance(filename, str) or not filename:
        raise HTTPException(400, "Upload metadata must contain a filename")
    media_type = mimetypes.guess_type(filename)[0]
    if media_type is None or not media_type.startswith("video/"):
        raise HTTPException(400, "Uploaded file must be a video")
    return filename


def parse_upload_id(upload_id: str) -> UUID:
    if not TUS_UPLOAD_ID_PATTERN.fullmatch(upload_id):
        raise HTTPException(400, "Invalid upload id")
    try:
        return UUID(upload_id)
    except ValueError as exc:
        raise HTTPException(400, "Invalid upload id") from exc


def tus_file_path(upload_id: UUID) -> str:
    return str(Path(config.TUSD_UPLOAD_DIR).resolve() / upload_id.hex)


def _header_values(headers: dict[str, Any], name: str) -> list[str]:
    values: list[str] = []
    for key, value in headers.items():
        if key.lower() != name.lower():
            continue
        entries = value if isinstance(value, list) else [value]
        values.extend(entry for entry in entries if isinstance(entry, str))
    return values
