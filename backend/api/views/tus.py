"""Blocking tusd hooks for upload registration and completion."""

from __future__ import annotations

import json
import logging
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.config import config
from api.db import get_session
from api.lib.tus import (
    TUS_HOOK_SECRET_HEADER,
    TusUploadEvent,
    tus_file_path,
)
from api.models.uploads import UserUploadCreate, UserUploads
from api.services.auth import authenticate_user
from api.services.uploads import (
    UploadConflictError,
    UploadNotFoundError,
    UserUploadsService,
)
from api.services.users import UserService

logger = logging.getLogger(__name__)
router = APIRouter()


def require_tus_hook_secret(request: Request) -> None:
    if not config.TUSD_HOOK_SECRET:
        raise HTTPException(503, "Upload hooks are not configured")
    supplied = request.headers.get(TUS_HOOK_SECRET_HEADER, "")
    if not secrets.compare_digest(
        supplied.encode("utf-8"),
        config.TUSD_HOOK_SECRET.encode("utf-8"),
    ):
        raise HTTPException(403, "Invalid upload hook credential")


def _rejection(status_code: int, detail: str) -> dict[str, Any]:
    """tusd expects creation rejections inside a successful hook response."""

    return {
        "HTTPResponse": {
            "StatusCode": status_code,
            "Body": json.dumps({"detail": detail}),
            "Header": {"Content-Type": "application/json"},
        },
        "RejectUpload": True,
    }


async def handle_pre_create(
    event: TusUploadEvent,
    session: AsyncSession,
) -> dict[str, Any]:
    if not event.bearer_token:
        raise HTTPException(401, "Missing bearer token")
    identity = await run_in_threadpool(
        authenticate_user,
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=event.bearer_token),
    )
    user = await UserService(session).sync_authenticated_user(identity)
    upload = await UserUploadsService(session).create(
        upload_id=event.upload_id,
        user_id=user.id,
        payload=UserUploadCreate(),
        filename=event.filename,
        size_bytes=event.size_bytes,
        file_path=tus_file_path(event.upload_id),
    )
    return {"ChangeFileInfo": {"ID": upload.id.hex}}


async def validate_completion(event: TusUploadEvent, session: AsyncSession) -> None:
    upload = await session.get(UserUploads, event.upload_id)
    if upload is None:
        raise UploadNotFoundError("Upload not found")
    if (
        event.filename != upload.filename
        or event.size_bytes != upload.size_bytes
        or event.offset != event.size_bytes
    ):
        raise UploadConflictError(
            "Upload completion does not match registered metadata"
        )


async def handle_pre_finish(
    event: TusUploadEvent,
    session: AsyncSession,
) -> dict[str, Any]:
    await validate_completion(event, session)
    await UserUploadsService(session).mark_uploaded(event.upload_id)
    return {}


@router.post("/hooks", status_code=status.HTTP_200_OK)
async def receive_tusd_hook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    require_tus_hook_secret(request)
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(400, "Invalid hook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Invalid hook payload")

    hook_type = payload.get("Type")
    if hook_type not in ("pre-create", "pre-finish"):
        return {}
    try:
        event = TusUploadEvent.from_hooks_payload(payload)
        if hook_type == "pre-create":
            return await handle_pre_create(event, session)
        return await handle_pre_finish(event, session)
    except (OSError, SQLAlchemyError) as exc:
        logger.exception("Upload hook database operation failed")
        # tusd retries HTTP 500 responses; a 503 would not trigger those retries.
        raise HTTPException(500, "Upload database is unavailable") from exc
    except UploadNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except UploadConflictError as exc:
        if hook_type == "pre-create":
            return _rejection(409, str(exc))
        raise HTTPException(409, str(exc)) from exc
    except HTTPException as exc:
        if hook_type == "pre-create":
            return _rejection(exc.status_code, str(exc.detail))
        raise
