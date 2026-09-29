import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.services.auth import require_user
from api.views import tus_proxy

UPSTREAM_BASE = "http://tusd:8080"


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
def tus_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.include_router(tus_proxy.router, prefix="/tus")
    app.dependency_overrides[require_user] = lambda: None
    with TestClient(app) as client:
        yield client


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
