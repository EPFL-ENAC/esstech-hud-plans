"""tusd webhook receiver for resumable video uploads.

tusd calls this endpoint on upload lifecycle events. The `pre-create` hook is
blocking: tusd rejects the upload creation when this endpoint answers with a
non-2xx status. The Authorization header of the original upload request is
forwarded inside the hook payload and validated here with the same JWT logic
as the rest of the API.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from api.services.auth import authenticate_user
from api.views.reconstruction_submission import validate_video_filename

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_bearer_token(headers: dict[str, Any]) -> str | None:
    """Read the bearer token from the forwarded request headers.

    tusd serializes header values as lists and preserves the original key
    casing, so the lookup is case-insensitive.
    """

    for key, value in headers.items():
        if not isinstance(key, str) or key.lower() != "authorization":
            continue
        entries = value if isinstance(value, list) else [value]
        for entry in entries:
            if isinstance(entry, str) and entry.lower().startswith("bearer "):
                return entry[len("bearer ") :].strip()
    return None


def _validate_hook_upload(upload: dict[str, Any]) -> None:
    """Check the upload metadata declared at creation time."""

    metadata = upload.get("MetaData") or {}
    validate_video_filename(
        metadata.get("filename") if isinstance(metadata, dict) else None
    )
    size = upload.get("Size")
    if (
        upload.get("SizeIsDeferred")
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size <= 0
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload size must be known and positive",
        )


@router.post("/hooks", status_code=status.HTTP_200_OK)
async def receive_tusd_hook(request: Request) -> dict[str, bool]:
    """Receive a tusd lifecycle hook.

    Only `pre-create` is blocking. Every other hook type is acknowledged so
    that enabling more tusd events later cannot break uploads.
    """

    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid hook payload",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid hook payload",
        )
    if payload.get("Type") != "pre-create":
        return {"ok": True}

    event = payload.get("Event") or {}
    if not isinstance(event, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid hook event",
        )

    http_request = event.get("HTTPRequest") or {}
    request_headers = (
        http_request.get("Headers") if isinstance(http_request, dict) else None
    )
    token = _extract_bearer_token(request_headers or {})
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    await run_in_threadpool(
        authenticate_user,
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=token),
    )

    upload = event.get("Upload") or {}
    if not isinstance(upload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid hook upload",
        )
    _validate_hook_upload(upload)

    return {"ok": True}
