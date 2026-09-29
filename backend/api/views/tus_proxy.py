"""Reverse proxy between the frontend and the tusd upload server.

The frontend only talks to this API. Upload requests under /tus/files are
forwarded to tusd at TUSD_INTERNAL_URL, so tusd stays on an internal network
and is never exposed. Proxy methods require an authenticated user; the
pre-create hook (/tus/hooks) checks the bearer token forwarded at upload
creation.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from api.config import config
from api.services.auth import require_user
from api.views.reconstruction_submission import TUS_UPLOAD_ID_PATTERN

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
            timeout=httpx.Timeout(10.0, read=120.0, write=120.0, pool=10.0),
        )
    return _client


async def close_tus_proxy() -> None:
    """Close the proxy HTTP client."""

    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _forwarded_request_headers(request: Request) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in FORWARDED_REQUEST_HEADERS
    }
    headers["X-Forwarded-For"] = request.client.host if request.client else ""
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Forwarded-Host"] = request.headers.get("host", "")
    return headers


def _proxied_location(request: Request, location: str) -> str:
    """Point the tusd upload location back at the API proxy."""

    upstream = httpx.URL(location)
    query = f"?{upstream.query.decode('ascii')}" if upstream.query else ""
    return f"{str(request.base_url).rstrip('/')}/tus{upstream.path}{query}"


async def _forward(request: Request, upstream_path: str) -> Response:
    body = request.stream() if request.method in ("POST", "PATCH") else None
    try:
        upstream = await _get_client().send(
            _get_client().build_request(
                request.method,
                upstream_path,
                headers=_forwarded_request_headers(request),
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
        await upstream.aclose()
        return Response(status_code=upstream.status_code, headers=forwarded)

    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=forwarded,
        background=BackgroundTask(upstream.aclose),
    )


def _checked_upload_id(upload_id: str) -> str:
    if not TUS_UPLOAD_ID_PATTERN.fullmatch(upload_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload id",
        )
    return upload_id


router = APIRouter()


@router.options("/files")
@router.options("/files/")
async def proxy_options(request: Request) -> Response:
    return await _forward(request, "/files/")


@router.post("/files", dependencies=[Depends(require_user)])
@router.post("/files/", dependencies=[Depends(require_user)])
async def proxy_create(request: Request) -> Response:
    return await _forward(request, "/files/")


@router.head("/files/{upload_id}", dependencies=[Depends(require_user)])
async def proxy_head(request: Request, upload_id: str) -> Response:
    return await _forward(request, f"/files/{_checked_upload_id(upload_id)}")


@router.patch("/files/{upload_id}", dependencies=[Depends(require_user)])
async def proxy_patch(request: Request, upload_id: str) -> Response:
    return await _forward(request, f"/files/{_checked_upload_id(upload_id)}")


@router.delete("/files/{upload_id}", dependencies=[Depends(require_user)])
async def proxy_delete(request: Request, upload_id: str) -> Response:
    return await _forward(request, f"/files/{_checked_upload_id(upload_id)}")
