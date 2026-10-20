"""Reverse proxy between the frontend and the tusd upload server.

The frontend only talks to this API. Upload requests under /tus/files are
forwarded to tusd at TUSD_INTERNAL_URL, so tusd stays on an internal network
and is never exposed. Proxy methods require an authenticated user; the
pre-create hook (/tus/hooks) checks the bearer token forwarded at upload
creation.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.background import BackgroundTask

from api.config import config
from api.lib.tus import (
    TUS_COMPLETION_TIMEOUT_SECONDS,
    TUS_HOOK_SECRET_HEADER,
    TUS_UPLOAD_ID_HEADER,
    parse_upload_id,
)
from api.lib.upload_storage import remove_tus_files
from api.models.uploads import UploadStatus, UserUploads
from api.models.user import User
from api.services.auth import require_user
from api.services.uploads import (
    UploadConflictError,
    UploadNotFoundError,
    UserUploadsService,
)
from api.views.uploads import get_uploads_service

logger = logging.getLogger(__name__)

# The browser must not send anything else to tusd. The whitelist keeps
# hop-by-hop headers and client fingerprinting headers out of tusd.
FORWARDED_REQUEST_HEADERS = {
    "authorization",
    "tus-resumable",
    "upload-length",
    "upload-offset",
    "upload-metadata",
    "upload-defer-length",
    "upload-concat",
    "content-type",
}

# The tus client reads these headers. Content-Length stays out so the
# response framing is computed for the proxied body.
FORWARDED_RESPONSE_HEADERS = {
    "location",
    "tus-resumable",
    "tus-version",
    "tus-extension",
    "tus-max-size",
    "tus-checksum-algorithm",
    "upload-offset",
    "upload-length",
    "upload-expires",
    "upload-metadata",
    "cache-control",
    "content-type",
}

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=config.TUSD_INTERNAL_URL,
            timeout=httpx.Timeout(
                10.0,
                read=TUS_COMPLETION_TIMEOUT_SECONDS + 30.0,
                write=120.0,
                pool=10.0,
            ),
        )
    return _client


async def close_tus_proxy() -> None:
    """Close the proxy HTTP client."""

    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _forwarded_request_headers(
    request: Request,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in FORWARDED_REQUEST_HEADERS
    }
    headers["X-Forwarded-For"] = request.client.host if request.client else ""
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Forwarded-Host"] = request.headers.get("host", "")
    if extra_headers:
        headers.update(extra_headers)
    if request.method != "OPTIONS":
        if not config.TUSD_HOOK_SECRET:
            raise HTTPException(503, "Upload hooks are not configured")
        headers[TUS_HOOK_SECRET_HEADER] = config.TUSD_HOOK_SECRET
    return headers


def _proxied_location(request: Request, location: str) -> str:
    """Point the tusd upload location back at the API proxy."""

    upstream = httpx.URL(location)
    query = f"?{upstream.query.decode('ascii')}" if upstream.query else ""
    return f"{str(request.base_url).rstrip('/')}/tus{upstream.path}{query}"


async def _forward(
    request: Request,
    upstream_path: str,
    *,
    extra_headers: dict[str, str] | None = None,
    on_head: Callable[[httpx.Response], Awaitable[None]] | None = None,
) -> Response:
    body = request.stream() if request.method in ("POST", "PATCH") else None
    try:
        upstream = await _get_client().send(
            _get_client().build_request(
                request.method,
                upstream_path,
                headers=_forwarded_request_headers(request, extra_headers),
                content=body,
            ),
            stream=True,
        )
    except httpx.TransportError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upload server is unreachable",
        ) from exc

    try:
        forwarded: dict[str, str] = {
            key: value
            for key, value in upstream.headers.multi_items()
            if key.lower() in FORWARDED_RESPONSE_HEADERS
        }
        location = upstream.headers.get("location")
        if location is not None:
            forwarded["location"] = _proxied_location(request, location)
    except (httpx.InvalidURL, UnicodeDecodeError) as exc:
        # The upstream response holds a connection, so it must not leak on a
        # malformed Location from tusd.
        await upstream.aclose()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Upload server returned an invalid response",
        ) from exc

    if request.method == "HEAD":
        try:
            if on_head is not None:
                await on_head(upstream)
            return Response(status_code=upstream.status_code, headers=forwarded)
        finally:
            await upstream.aclose()

    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=forwarded,
        background=BackgroundTask(upstream.aclose),
    )


async def get_owned_tus_upload(
    upload_id: str,
    current_user: Annotated[User, Depends(require_user)],
    uploads: Annotated[UserUploadsService, Depends(get_uploads_service)],
) -> UserUploads:
    parsed_id = parse_upload_id(upload_id)
    try:
        upload = await uploads.get(parsed_id, user_id=current_user.id)
    except (OSError, SQLAlchemyError) as exc:
        logger.exception("Upload proxy database operation failed")
        raise HTTPException(503, "Upload database is unavailable") from exc
    if upload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )
    return upload


CurrentTusUpload = Annotated[UserUploads, Depends(get_owned_tus_upload)]
UploadsService = Annotated[UserUploadsService, Depends(get_uploads_service)]


async def reconcile_head(
    response: httpx.Response,
    upload: UserUploads,
    uploads: UserUploadsService,
) -> None:
    if upload.status != UploadStatus.PENDING:
        return
    if (
        response.is_success
        and upload.size_bytes > 0
        and response.headers.get("Upload-Length") == str(upload.size_bytes)
        and response.headers.get("Upload-Offset") == str(upload.size_bytes)
    ):
        try:
            await uploads.complete(upload.id)
        except (OSError, SQLAlchemyError) as exc:
            logger.exception("Upload HEAD persistence failed")
            raise HTTPException(503, "Upload persistence is unavailable") from exc
        except UploadNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except UploadConflictError as exc:
            raise HTTPException(409, str(exc)) from exc


async def require_stored_upload(
    upload: UserUploads,
    uploads: UserUploadsService,
) -> UserUploads:
    try:
        return await uploads.get_completed(upload.id, user_id=upload.user_id)
    except UploadNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except UploadConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (OSError, SQLAlchemyError) as exc:
        logger.exception("Stored upload is unavailable")
        raise HTTPException(503, "Upload persistence is unavailable") from exc


def completed_upload_response(upload: UserUploads, status_code: int) -> Response:
    filename = base64.b64encode(upload.filename.encode("utf-8")).decode("ascii")
    return Response(
        status_code=status_code,
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": str(upload.size_bytes),
            "Upload-Length": str(upload.size_bytes),
            "Upload-Metadata": f"filename {filename}",
            "Cache-Control": "no-store",
        },
    )


router = APIRouter()


@router.options("/files")
@router.options("/files/")
async def proxy_options(request: Request) -> Response:
    return await _forward(request, "/files/")


@router.post("/files", dependencies=[Depends(require_user)])
@router.post("/files/", dependencies=[Depends(require_user)])
async def proxy_create(request: Request) -> Response:
    return await _forward(
        request,
        "/files/",
        extra_headers={TUS_UPLOAD_ID_HEADER: uuid4().hex},
    )


@router.head("/files/{upload_id}")
async def proxy_head(
    request: Request,
    upload: Annotated[UserUploads, Depends(get_owned_tus_upload)],
    uploads: Annotated[UserUploadsService, Depends(get_uploads_service)],
) -> Response:
    if upload.status == UploadStatus.UPLOADED:
        try:
            stored = await uploads.complete(upload.id)
        except UploadNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except UploadConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (OSError, SQLAlchemyError) as exc:
            logger.exception("Upload HEAD persistence or dispatch failed")
            raise HTTPException(503, "Upload persistence is unavailable") from exc
        return completed_upload_response(stored, 200)

    async def on_head(response: httpx.Response) -> None:
        await reconcile_head(response, upload, uploads)

    return await _forward(request, f"/files/{upload.id.hex}", on_head=on_head)


@router.patch("/files/{upload_id}")
async def proxy_patch(
    request: Request,
    upload: CurrentTusUpload,
    uploads: UploadsService,
) -> Response:
    if upload.status == UploadStatus.UPLOADED:
        stored = await require_stored_upload(upload, uploads)
        if request.headers.get("Tus-Resumable") != "1.0.0":
            raise HTTPException(412, "Unsupported tus version")
        if request.headers.get("Content-Type") != "application/offset+octet-stream":
            raise HTTPException(415, "Invalid upload content type")
        if request.headers.get("Upload-Offset") != str(stored.size_bytes):
            raise HTTPException(409, "Upload offset does not match completed upload")
        async for chunk in request.stream():
            if chunk:
                raise HTTPException(409, "Upload is already complete")
        return completed_upload_response(stored, 204)

    return await _forward(request, f"/files/{upload.id.hex}")


@router.delete("/files/{upload_id}")
async def proxy_delete(
    request: Request,
    upload: CurrentTusUpload,
    uploads: UploadsService,
) -> Response:
    try:
        uploads.require_uploaded(upload)
    except UploadConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    await require_stored_upload(upload, uploads)
    try:
        remove_tus_files(upload.id)
    except OSError as exc:
        raise HTTPException(503, "Upload staging cleanup is unavailable") from exc
    return Response(status_code=204, headers={"Tus-Resumable": "1.0.0"})
