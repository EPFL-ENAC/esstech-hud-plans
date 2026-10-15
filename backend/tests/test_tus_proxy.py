import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from api.config import config
from api.db import get_session
from api.lib.tus import TUS_HOOK_SECRET_HEADER, TUS_UPLOAD_ID_HEADER
from api.lib.upload_storage import upload_file_path
from api.models.uploads import UploadStatus, UserUploadRead, UserUploads
from api.models.user import User
from api.services.auth import require_user
from api.services.uploads import UserUploadsService
from api.views import tus_proxy

UPSTREAM_BASE = "http://tusd:8080"
USER_ID = UUID(int=1)
OTHER_USER_ID = UUID(int=2)


@pytest.fixture(autouse=True)
def upload_directories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "TUSD_UPLOAD_DIR", str(tmp_path / "tus"))
    Path(config.TUSD_UPLOAD_DIR).mkdir()


@pytest.fixture(autouse=True)
def hook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TUSD_HOOK_SECRET", "test-hook-secret")


# Mock responses must carry their body as a stream. A response built with
# content= reads its body at construction, and the proxy would then find the
# upstream stream already consumed.
def _upstream_response(
    status_code: int,
    headers: dict[str, str] | None = None,
    content: bytes = b"",
) -> httpx.Response:
    return httpx.Response(
        status_code, headers=headers, stream=httpx.ByteStream(content)
    )


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[tuple[str, str], httpx.Response],
    received: list[httpx.Request],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        received.append(request)
        key = (request.method, request.url.path)
        assert key in responses, f"unexpected upstream request {key}"
        return responses[key]

    client = httpx.AsyncClient(
        base_url=UPSTREAM_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(tus_proxy, "_get_client", lambda: client)


@pytest.fixture
def tus_client() -> Iterator[TestClient]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    User(id=USER_ID, keycloak_sub="subject-1"),
                    User(id=OTHER_USER_ID, keycloak_sub="subject-2"),
                    *[
                        UserUploads(
                            id=UUID(character * 32),
                            user_id=USER_ID,
                            filename="video.mp4",
                            size_bytes=11,
                            file_path=str(
                                Path(config.TUSD_UPLOAD_DIR) / (character * 32)
                            ),
                        )
                        for character in ("c", "d")
                    ],
                ]
            )
            await session.commit()

    for character in ("c", "d"):
        staging = Path(config.TUSD_UPLOAD_DIR) / (character * 32)
        staging.write_bytes(b"video bytes")
        staging.with_name(staging.name + ".info").write_text("{}")
    asyncio.run(prepare())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app = FastAPI()
    app.state.upload_database = engine
    app.include_router(tus_proxy.router, prefix="/tus")
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[require_user] = lambda: User(
        id=USER_ID,
        keycloak_sub="subject-1",
    )
    with TestClient(app) as client:
        yield client
    asyncio.run(engine.dispose())


def _read_proxy_upload(tus_client: TestClient, upload_id: UUID) -> UserUploadRead:
    assert isinstance(tus_client.app, FastAPI)
    engine = tus_client.app.state.upload_database

    async def read() -> UserUploadRead:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            upload = await session.get(UserUploads, upload_id)
            assert upload is not None
            return UserUploadRead.model_validate(upload)

    return asyncio.run(read())


def test_create_forwards_headers_and_rewrites_location(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    received: list[httpx.Request] = []
    _install_transport(
        monkeypatch,
        {
            ("POST", "/files/"): _upstream_response(
                201,
                headers={
                    "Location": f"{UPSTREAM_BASE}/files/{'a' * 32}",
                    "Tus-Resumable": "1.0.0",
                    "Connection": "keep-alive",
                    "Server": "tusd",
                },
            )
        },
        received,
    )

    response = tus_client.post(
        "/tus/files/",
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Length": "11",
            "Authorization": "Bearer token",
            "X-Custom": "drop-me",
            TUS_UPLOAD_ID_HEADER: "client-cannot-pick-this-id",
            TUS_HOOK_SECRET_HEADER: "client-cannot-pick-this-secret",
        },
    )

    assert response.status_code == 201
    assert response.headers["location"] == f"http://testserver/tus/files/{'a' * 32}"
    assert response.headers["tus-resumable"] == "1.0.0"
    assert "connection" not in response.headers
    assert "server" not in response.headers

    upstream = received[0]
    assert upstream.method == "POST"
    assert upstream.url.path == "/files/"
    assert upstream.headers["upload-length"] == "11"
    assert upstream.headers["tus-resumable"] == "1.0.0"
    assert upstream.headers["authorization"] == "Bearer token"
    assert upstream.headers["host"] == "tusd:8080"
    assert "x-custom" not in upstream.headers
    assert UUID(upstream.headers[TUS_UPLOAD_ID_HEADER])
    assert upstream.headers[TUS_HOOK_SECRET_HEADER] == "test-hook-secret"
    assert TUS_HOOK_SECRET_HEADER.lower() not in response.headers


def test_create_without_trailing_slash_reaches_tusd(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    received: list[httpx.Request] = []
    _install_transport(
        monkeypatch,
        {("POST", "/files/"): _upstream_response(201)},
        received,
    )

    response = tus_client.post("/tus/files", headers={"Tus-Resumable": "1.0.0"})

    assert response.status_code == 201
    assert received[0].url.path == "/files/"


def test_create_with_root_path_rewrites_location_under_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[httpx.Request] = []
    _install_transport(
        monkeypatch,
        {
            ("POST", "/files/"): _upstream_response(
                201,
                headers={"Location": f"{UPSTREAM_BASE}/files/{'b' * 32}"},
            )
        },
        received,
    )

    app = FastAPI(root_path="/api")
    app.include_router(tus_proxy.router, prefix="/tus")
    app.dependency_overrides[require_user] = lambda: None
    with TestClient(app) as client:
        response = client.post("/api/tus/files/", headers={"Tus-Resumable": "1.0.0"})

    assert response.status_code == 201
    assert response.headers["location"] == f"http://testserver/api/tus/files/{'b' * 32}"


def test_patch_streams_body_and_forwards_offset(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    upload_id = "c" * 32
    received: list[httpx.Request] = []
    _install_transport(
        monkeypatch,
        {
            ("PATCH", f"/files/{upload_id}"): _upstream_response(
                204,
                headers={"Upload-Offset": "11", "Tus-Resumable": "1.0.0"},
            )
        },
        received,
    )

    response = tus_client.patch(
        f"/tus/files/{upload_id}",
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": "0",
            "Content-Type": "application/offset+octet-stream",
        },
        content=b"video bytes",
    )

    assert response.status_code == 204
    assert response.headers["upload-offset"] == "11"

    upstream = received[0]
    assert upstream.content == b"video bytes"
    assert upstream.headers["upload-offset"] == "0"
    assert upstream.headers["content-type"] == "application/offset+octet-stream"


def test_head_forwards_offset_and_returns_no_body(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    upload_id = "d" * 32
    received: list[httpx.Request] = []
    _install_transport(
        monkeypatch,
        {
            ("HEAD", f"/files/{upload_id}"): _upstream_response(
                200,
                headers={
                    "Upload-Offset": "11",
                    "Upload-Length": "11",
                    "Cache-Control": "no-store",
                    "Content-Length": "11",
                },
            )
        },
        received,
    )

    response = tus_client.head(f"/tus/files/{upload_id}")

    assert response.status_code == 200
    assert response.headers["upload-offset"] == "11"
    assert response.headers["upload-length"] == "11"
    assert response.headers["cache-control"] == "no-store"
    assert response.content == b""
    completed = _read_proxy_upload(tus_client, UUID(upload_id))
    assert completed.status == UploadStatus.UPLOADED
    assert completed.uploaded_at is not None


def test_options_forwards_tus_capabilities(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    received: list[httpx.Request] = []
    _install_transport(
        monkeypatch,
        {
            ("OPTIONS", "/files/"): _upstream_response(
                204,
                headers={
                    "Tus-Version": "1.0.0",
                    "Tus-Extension": "creation,termination",
                    "Tus-Max-Size": "1073741824",
                },
            )
        },
        received,
    )

    response = tus_client.options("/tus/files/")

    assert response.status_code == 204
    assert response.headers["tus-version"] == "1.0.0"
    assert response.headers["tus-extension"] == "creation,termination"
    assert response.headers["tus-max-size"] == "1073741824"


@pytest.mark.parametrize(
    "upload_id, expected_status",
    [
        ("a" * 65, 400),
        ("id with space", 400),
        ("not<hex>", 400),
        # Starlette path parameters never match slashes and httpx normalizes
        # "..", so a traversal id is rejected as 404 before the proxy runs.
        ("../escape", 404),
        ("a/b", 404),
    ],
)
def test_proxy_rejects_unsafe_upload_ids(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
    upload_id: str,
    expected_status: int,
) -> None:
    received: list[httpx.Request] = []
    _install_transport(monkeypatch, {}, received)

    response = tus_client.head(f"/tus/files/{upload_id}")

    assert response.status_code == expected_status
    assert received == []


def test_proxy_returns_502_when_tusd_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.AsyncClient(
        base_url=UPSTREAM_BASE,
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(tus_proxy, "_get_client", lambda: client)

    response = tus_client.post("/tus/files/", headers={"Tus-Resumable": "1.0.0"})

    assert response.status_code == 502


def test_proxy_requires_authenticated_user() -> None:
    app = FastAPI()
    app.include_router(tus_proxy.router, prefix="/tus")
    with TestClient(app) as client:
        assert client.patch(f"/tus/files/{'e' * 32}").status_code == 401
        assert client.delete(f"/tus/files/{'e' * 32}").status_code == 401


def _complete_proxy_upload(tus_client: TestClient, upload_id: UUID) -> None:
    assert isinstance(tus_client.app, FastAPI)
    engine = tus_client.app.state.upload_database

    async def complete() -> None:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await UserUploadsService(session).complete(upload_id)

    asyncio.run(complete())


def test_pending_tus_delete_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    upload_id = UUID("c" * 32)
    before = _read_proxy_upload(tus_client, upload_id)
    received: list[httpx.Request] = []
    _install_transport(monkeypatch, {}, received)
    response = tus_client.delete(f"/tus/files/{upload_id.hex}")
    assert response.status_code == 409
    assert response.json() == {"detail": "Upload has not finished uploading"}
    assert received == []
    assert _read_proxy_upload(tus_client, upload_id) == before


def test_completed_tus_delete_preserves_stored_file(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    upload_id = UUID("c" * 32)
    _complete_proxy_upload(tus_client, upload_id)
    received: list[httpx.Request] = []
    _install_transport(
        monkeypatch,
        {("DELETE", f"/files/{upload_id.hex}"): _upstream_response(204)},
        received,
    )
    response = tus_client.delete(f"/tus/files/{upload_id.hex}")
    assert response.status_code == 204
    assert response.content == b""
    assert received == []
    assert upload_file_path(upload_id, "video.mp4").read_bytes() == b"video bytes"
    assert _read_proxy_upload(tus_client, upload_id).status == UploadStatus.UPLOADED


@pytest.mark.parametrize("method", ["HEAD", "PATCH", "DELETE"])
@pytest.mark.parametrize("other_user", [False, True])
def test_proxy_hides_unowned_or_unknown_uploads(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
    method: str,
    other_user: bool,
) -> None:
    assert isinstance(tus_client.app, FastAPI)
    if other_user:
        tus_client.app.dependency_overrides[require_user] = lambda: User(
            id=OTHER_USER_ID,
            keycloak_sub="subject-2",
        )
    upload_id = "c" * 32 if other_user else "e" * 32
    received: list[httpx.Request] = []
    _install_transport(monkeypatch, {}, received)
    assert tus_client.request(method, f"/tus/files/{upload_id}").status_code == 404
    assert received == []


@pytest.mark.parametrize(
    ("status_code", "offset", "length"),
    [
        (200, "5", "11"),
        (200, "11", "12"),
        (200, "invalid", "11"),
        (200, "11", None),
        (404, "11", "11"),
        (500, "11", "11"),
    ],
)
def test_head_does_not_complete_partial_or_invalid_upstream_state(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
    status_code: int,
    offset: str,
    length: str | None,
) -> None:
    headers = {"Upload-Offset": offset}
    if length is not None:
        headers["Upload-Length"] = length
    upstream = _upstream_response(status_code, headers=headers)
    received: list[httpx.Request] = []
    _install_transport(
        monkeypatch, {("HEAD", f"/files/{'d' * 32}"): upstream}, received
    )
    response = tus_client.head(f"/tus/files/{'d' * 32}")
    assert response.status_code == status_code
    assert _read_proxy_upload(tus_client, UUID("d" * 32)).status == UploadStatus.PENDING
    assert upstream.is_closed


def test_head_closes_upstream_on_database_failure(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    upstream = _upstream_response(
        200,
        headers={"Upload-Offset": "11", "Upload-Length": "11"},
    )
    received: list[httpx.Request] = []
    _install_transport(
        monkeypatch, {("HEAD", f"/files/{'d' * 32}"): upstream}, received
    )
    monkeypatch.setattr(
        UserUploadsService,
        "complete",
        AsyncMock(side_effect=OSError("database unavailable")),
    )
    response = tus_client.head(f"/tus/files/{'d' * 32}")
    assert response.status_code == 503
    assert upstream.is_closed
    assert _read_proxy_upload(tus_client, UUID("d" * 32)).status == UploadStatus.PENDING


def test_head_does_not_rewrite_completed_upload(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    upload_id = UUID("d" * 32)
    _complete_proxy_upload(tus_client, upload_id)
    before = _read_proxy_upload(tus_client, upload_id)
    received: list[httpx.Request] = []
    _install_transport(
        monkeypatch,
        {
            ("HEAD", f"/files/{upload_id.hex}"): _upstream_response(
                200,
                headers={"Upload-Offset": "11", "Upload-Length": "11"},
            )
        },
        received,
    )
    assert tus_client.head(f"/tus/files/{upload_id.hex}").status_code == 200
    assert received == []
    assert _read_proxy_upload(tus_client, upload_id) == before


def test_completed_head_reports_metadata_without_tusd(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    upload_id = UUID("c" * 32)
    _complete_proxy_upload(tus_client, upload_id)
    received: list[httpx.Request] = []
    _install_transport(monkeypatch, {}, received)
    response = tus_client.head(f"/tus/files/{upload_id.hex}")
    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["Upload-Offset"] == "11"
    assert response.headers["Upload-Length"] == "11"
    assert response.headers["Tus-Resumable"] == "1.0.0"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Upload-Metadata"] == "filename dmlkZW8ubXA0"
    assert received == []


@pytest.mark.parametrize("method", ["HEAD", "PATCH", "DELETE"])
def test_completed_requests_verify_permanent_file(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
    method: str,
) -> None:
    upload_id = UUID("c" * 32)
    _complete_proxy_upload(tus_client, upload_id)
    upload_file_path(upload_id, "video.mp4").unlink()
    received: list[httpx.Request] = []
    _install_transport(monkeypatch, {}, received)
    assert tus_client.request(method, f"/tus/files/{upload_id.hex}").status_code == 503
    assert received == []


@pytest.mark.parametrize(
    ("offset", "content", "expected_status"),
    [("11", b"", 204), ("0", b"", 409), ("11", b"extra", 409)],
)
def test_completed_patch_only_accepts_empty_retry_at_final_offset(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
    offset: str,
    content: bytes,
    expected_status: int,
) -> None:
    upload_id = UUID("c" * 32)
    _complete_proxy_upload(tus_client, upload_id)
    received: list[httpx.Request] = []
    _install_transport(monkeypatch, {}, received)
    response = tus_client.patch(
        f"/tus/files/{upload_id.hex}",
        headers={
            "Tus-Resumable": "1.0.0",
            "Content-Type": "application/offset+octet-stream",
            "Upload-Offset": offset,
        },
        content=content,
    )
    assert response.status_code == expected_status
    if expected_status == 204:
        assert response.headers["Upload-Offset"] == "11"
    assert upload_file_path(upload_id, "video.mp4").read_bytes() == b"video bytes"
    assert received == []


def test_proxy_database_failure_prevents_upstream_request(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    received: list[httpx.Request] = []
    _install_transport(monkeypatch, {}, received)
    monkeypatch.setattr(
        UserUploadsService,
        "get",
        AsyncMock(side_effect=OSError("database unavailable")),
    )
    assert tus_client.head(f"/tus/files/{'c' * 32}").status_code == 503
    assert received == []


def test_proxy_requires_configured_hook_secret(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    monkeypatch.setattr(config, "TUSD_HOOK_SECRET", "")
    received: list[httpx.Request] = []
    _install_transport(monkeypatch, {}, received)
    response = tus_client.post("/tus/files/", headers={"Tus-Resumable": "1.0.0"})
    assert response.status_code == 503
    assert received == []


def test_proxy_closes_upstream_on_invalid_location(
    monkeypatch: pytest.MonkeyPatch,
    tus_client: TestClient,
) -> None:
    upstream = _upstream_response(
        201, headers={"Location": "http://tusd:invalid/files/id"}
    )
    received: list[httpx.Request] = []
    _install_transport(monkeypatch, {("POST", "/files/"): upstream}, received)
    assert tus_client.post("/tus/files/").status_code == 502
    assert upstream.is_closed
