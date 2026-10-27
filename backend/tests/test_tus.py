import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from api.config import config
from api.db import get_session
from api.lib.tus import TUS_HOOK_SECRET_HEADER, TUS_UPLOAD_ID_HEADER
from api.lib.upload_storage import upload_file_path
from api.lib.workflows import common as workflow_common
from api.lib.workflows import splat_generation as splat_workflow
from api.lib.workflows import tus_cleanup
from api.models.auth import AuthenticatedUser
from api.models.building import Building
from api.models.uploads import UploadStatus, UserUploads
from api.models.user import User
from api.services.auth import require_user
from api.services.uploads import UserUploadsService
from api.views import buildings as building_views
from api.views import reconstructions as reconstruction_views
from api.views import tus as tus_views

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
BUILDING_ID = UUID("10000000-0000-0000-0000-000000000001")
WORKFLOW_ID = UUID("20000000-0000-0000-0000-000000000001")
UPLOAD_ID = UUID("30000000-0000-0000-0000-000000000001")


def _hook_payload(
    *,
    hook_type: str = "pre-create",
    headers: dict[str, object] | None = None,
    filename: str = "scan.mp4",
    size: object = 11,
    size_is_deferred: bool = False,
    offset: int | None = None,
) -> dict[str, Any]:
    request_headers: dict[str, object] = (
        {"Authorization": ["Bearer forwarded-token"]}
        if headers is None
        else dict(headers)
    )
    request_headers[TUS_UPLOAD_ID_HEADER] = [UPLOAD_ID.hex]
    return {
        "Type": hook_type,
        "Event": {
            "Upload": {
                "ID": UPLOAD_ID.hex if hook_type != "pre-create" else None,
                "Size": size,
                "SizeIsDeferred": size_is_deferred,
                "Offset": (
                    offset
                    if offset is not None
                    else size
                    if hook_type == "pre-finish"
                    else 0
                ),
                "MetaData": {"filename": filename},
                "IsPartial": False,
                "IsFinal": False,
                "Storage": None,
            },
            "HTTPRequest": {
                "Method": "POST",
                "URI": "/files/",
                "Header": request_headers,
            },
        },
    }


def _accept_any_token(
    received: list[HTTPAuthorizationCredentials],
) -> Callable[[HTTPAuthorizationCredentials], AuthenticatedUser]:
    def authenticate(
        credentials: HTTPAuthorizationCredentials,
    ) -> AuthenticatedUser:
        received.append(credentials)
        return AuthenticatedUser(sub="subject-1")

    return authenticate


@pytest.fixture(autouse=True)
def upload_directories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "TUSD_UPLOAD_DIR", str(tmp_path / "default-tus"))
    Path(config.TUSD_UPLOAD_DIR).mkdir()


@pytest.fixture
def tus_hook_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(config, "TUSD_HOOK_SECRET", "test-hook-secret")
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(User(id=USER_ID, keycloak_sub="subject-1"))
            await session.commit()

    asyncio.run(prepare())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app = FastAPI()
    app.include_router(tus_views.router, prefix="/tus")
    app.dependency_overrides[get_session] = session_override
    app.state.upload_database = engine
    with TestClient(app) as client:
        client.headers[TUS_HOOK_SECRET_HEADER] = "test-hook-secret"
        yield client
    asyncio.run(engine.dispose())


def _read_hook_upload(tus_hook_api: TestClient) -> UserUploads | None:
    assert isinstance(tus_hook_api.app, FastAPI)
    engine = tus_hook_api.app.state.upload_database

    async def read() -> UserUploads | None:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await session.get(UserUploads, UPLOAD_ID)

    return asyncio.run(read())


def _make_tus_upload(
    directory: Path,
    upload_id: str,
    *,
    filename: str = "scan.mp4",
    content: bytes = b"video bytes",
    with_info: bool = True,
    size: int | None = None,
    size_is_deferred: bool = False,
) -> Path:
    binary = directory / upload_id
    binary.write_bytes(content)
    if with_info:
        info = {
            "ID": upload_id,
            "Size": size if size is not None else len(content),
            "SizeIsDeferred": size_is_deferred,
            "Offset": len(content),
            "MetaData": {"filename": filename},
            "IsPartial": False,
            "IsFinal": False,
            "Storage": {"Type": "filestore", "Path": str(binary)},
        }
        (directory / f"{upload_id}.info").write_text(json.dumps(info))
    return binary


def test_hook_accepts_valid_pre_create(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
) -> None:
    received: list[HTTPAuthorizationCredentials] = []
    monkeypatch.setattr(tus_views, "authenticate_user", _accept_any_token(received))

    response = tus_hook_api.post("/tus/hooks", json=_hook_payload())

    assert response.status_code == 200
    assert response.json() == {"ChangeFileInfo": {"ID": UPLOAD_ID.hex}}
    upload = _read_hook_upload(tus_hook_api)
    assert upload is not None
    assert upload.user_id == USER_ID
    assert upload.filename == "scan.mp4"
    assert upload.size_bytes == 11
    assert upload.name == "TODO"
    assert upload.description == ""
    assert upload.file_path == str(
        Path(config.TUSD_UPLOAD_DIR).resolve() / UPLOAD_ID.hex
    )
    assert upload.status == UploadStatus.PENDING
    assert upload.uploaded_bytes == 0
    assert upload.uploaded_at is None
    assert len(received) == 1
    assert received[0].scheme == "Bearer"
    assert received[0].credentials == "forwarded-token"


def test_hook_reads_case_insensitive_authorization_header(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
) -> None:
    received: list[HTTPAuthorizationCredentials] = []
    monkeypatch.setattr(tus_views, "authenticate_user", _accept_any_token(received))

    response = tus_hook_api.post(
        "/tus/hooks",
        json=_hook_payload(headers={"authorization": ["Bearer forwarded-token"]}),
    )

    assert response.status_code == 200
    assert received[0].credentials == "forwarded-token"


def test_hook_rejects_missing_authorization(
    tus_hook_api: TestClient,
) -> None:
    response = tus_hook_api.post("/tus/hooks", json=_hook_payload(headers={}))

    assert response.status_code == 200
    assert response.json() == {
        "RejectUpload": True,
        "HTTPResponse": {
            "StatusCode": 401,
            "Body": '{"detail": "Missing bearer token"}',
            "Header": {"Content-Type": "application/json"},
        },
    }


def test_hook_rejects_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
) -> None:
    def fail_authentication(credentials: HTTPAuthorizationCredentials) -> object:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    monkeypatch.setattr(tus_views, "authenticate_user", fail_authentication)

    response = tus_hook_api.post("/tus/hooks", json=_hook_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["RejectUpload"] is True
    assert body["HTTPResponse"]["StatusCode"] == 401
    assert json.loads(body["HTTPResponse"]["Body"]) == {
        "detail": "Invalid or expired token"
    }


def test_hook_rejects_non_video_filename(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
) -> None:
    received: list[HTTPAuthorizationCredentials] = []
    monkeypatch.setattr(tus_views, "authenticate_user", _accept_any_token(received))

    response = tus_hook_api.post("/tus/hooks", json=_hook_payload(filename="notes.pdf"))

    assert response.status_code == 200
    body = response.json()
    assert body["RejectUpload"] is True
    assert body["HTTPResponse"]["StatusCode"] == 400
    assert len(received) == 0
    assert _read_hook_upload(tus_hook_api) is None


@pytest.mark.parametrize(
    "size, size_is_deferred",
    [(0, False), (None, True), (11, True)],
)
def test_hook_rejects_unknown_or_empty_size(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
    size: object,
    size_is_deferred: bool,
) -> None:
    received: list[HTTPAuthorizationCredentials] = []
    monkeypatch.setattr(tus_views, "authenticate_user", _accept_any_token(received))

    response = tus_hook_api.post(
        "/tus/hooks",
        json=_hook_payload(size=size, size_is_deferred=size_is_deferred),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["RejectUpload"] is True
    assert body["HTTPResponse"]["StatusCode"] == 400


def test_hook_acknowledges_other_hook_types(tus_hook_api: TestClient) -> None:
    response = tus_hook_api.post(
        "/tus/hooks", json=_hook_payload(hook_type="post-finish")
    )

    assert response.status_code == 200
    assert response.json() == {}


def test_hook_rejects_invalid_payload(tus_hook_api: TestClient) -> None:
    response = tus_hook_api.post(
        "/tus/hooks",
        content=b"not json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400


def test_hook_rejects_non_dict_payload(tus_hook_api: TestClient) -> None:
    response = tus_hook_api.post("/tus/hooks", json=[1, 2])

    assert response.status_code == 400


@pytest.fixture
def tus_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[tuple[TestClient, UUID, Path]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )
    tus_dir = tmp_path / "tus-uploads"
    tus_dir.mkdir()
    monkeypatch.setattr(
        workflow_common, "WORKFLOW_DATA_DIRECTORY", tmp_path / "workflows"
    )
    monkeypatch.setattr(config, "TUSD_UPLOAD_DIR", str(tus_dir))

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    User(id=USER_ID, keycloak_sub="subject-1"),
                    Building(
                        id=BUILDING_ID,
                        user_id=USER_ID,
                        name="BC",
                        latitude=46.518,
                        longitude=6.563,
                    ),
                ]
            )
            await session.commit()

    asyncio.run(prepare_database())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async def fake_schedule(**kwargs: object) -> UUID:
        return WORKFLOW_ID

    monkeypatch.setattr(
        splat_workflow, "schedule_splat_generation_from_tus", fake_schedule
    )

    app = FastAPI()
    app.state.upload_database = engine
    app.include_router(building_views.router, prefix="/buildings")
    app.include_router(
        reconstruction_views.router,
        prefix="/buildings/{building_id}/reconstructions",
    )
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[require_user] = lambda: User(
        id=USER_ID,
        keycloak_sub="subject-1",
        terms_accepted_version=config.TERMS_VERSION,
    )

    with TestClient(app) as client:
        yield client, BUILDING_ID, tus_dir

    asyncio.run(engine.dispose())


def _register_tus_upload(
    client: TestClient,
    upload_id: str,
    *,
    filename: str = "scan.mp4",
    size_bytes: int = 11,
    status: UploadStatus = UploadStatus.UPLOADED,
    user_id: UUID = USER_ID,
) -> None:
    assert isinstance(client.app, FastAPI)

    async def register() -> None:
        async with AsyncSession(client.app.state.upload_database) as session:
            if await session.get(User, user_id) is None:
                session.add(User(id=user_id, keycloak_sub=str(user_id)))
                await session.flush()
            session.add(
                UserUploads(
                    id=UUID(upload_id),
                    user_id=user_id,
                    filename=filename,
                    size_bytes=size_bytes,
                    file_path=str(Path(config.TUSD_UPLOAD_DIR) / upload_id),
                    status=status,
                )
            )
            await session.commit()

    asyncio.run(register())


def test_from_upload_reconstruction_submission_schedules_copy(
    tus_api: tuple[TestClient, UUID, Path],
) -> None:
    client, building_id, tus_dir = tus_api
    upload_id = uuid4().hex
    _make_tus_upload(tus_dir, upload_id)
    _register_tus_upload(client, upload_id)

    response = client.post(
        f"/buildings/{building_id}/reconstructions/from-upload",
        json={"upload_id": upload_id, "settings": {}},
    )

    assert response.status_code == 202
    created = response.json()
    assert created["status"] == "scheduled"
    assert created["prefect_workflow_id"] == str(WORKFLOW_ID)
    assert created["input_video_path"].endswith("video/input.mp4")


def test_from_upload_reconstruction_submission_passes_tus_parameters(
    monkeypatch: pytest.MonkeyPatch,
    tus_api: tuple[TestClient, UUID, Path],
) -> None:
    client, building_id, tus_dir = tus_api
    upload_id = uuid4().hex
    _make_tus_upload(tus_dir, upload_id, filename="recording.mov")
    _register_tus_upload(client, upload_id, filename="recording.mov")

    async def complete() -> None:
        async with AsyncSession(
            client.app.state.upload_database, expire_on_commit=False
        ) as session:
            await UserUploadsService(session).complete(UUID(upload_id))

    asyncio.run(complete())
    captured: dict[str, object] = {}

    async def fake_schedule(**kwargs: object) -> UUID:
        captured.update(kwargs)
        return WORKFLOW_ID

    monkeypatch.setattr(
        splat_workflow, "schedule_splat_generation_from_tus", fake_schedule
    )

    response = client.post(
        f"/buildings/{building_id}/reconstructions/from-upload",
        json={"upload_id": upload_id, "settings": {"ffmpeg": {"fps": 4}}},
    )

    assert response.status_code == 202
    created = response.json()
    assert captured["tus_upload_path"] == str(
        upload_file_path(UUID(upload_id), "recording.mov")
    )
    assert captured["tus_video_filename"] == "recording.mov"
    assert captured["owner_id"] == USER_ID
    assert captured["reconstruction_id"] == UUID(created["id"])
    parameters = captured["artifact"]
    assert isinstance(parameters, splat_workflow.SplatGenerationArtifact)
    assert str(parameters.video_path).endswith("video/input.mov")


def test_permanent_upload_can_be_submitted_twice(
    monkeypatch: pytest.MonkeyPatch,
    tus_api: tuple[TestClient, UUID, Path],
) -> None:
    async def schedule(**kwargs: object) -> UUID:
        return uuid4()

    monkeypatch.setattr(splat_workflow, "schedule_splat_generation_from_tus", schedule)
    client, building_id, tus_dir = tus_api
    upload_id = uuid4().hex
    _make_tus_upload(tus_dir, upload_id)
    _register_tus_upload(client, upload_id)

    async def complete() -> None:
        async with AsyncSession(
            client.app.state.upload_database, expire_on_commit=False
        ) as session:
            await UserUploadsService(session).complete(UUID(upload_id))

    asyncio.run(complete())
    url = f"/buildings/{building_id}/reconstructions/from-upload"
    first = client.post(url, json={"upload_id": upload_id})
    assert first.status_code == 202
    assert not (tus_dir / upload_id).exists()
    second = client.post(url, json={"upload_id": upload_id})
    assert second.status_code == 202
    assert first.json()["id"] != second.json()["id"]
    assert upload_file_path(UUID(upload_id), "scan.mp4").read_bytes() == b"video bytes"


@pytest.mark.parametrize("new_building", [False, True])
@pytest.mark.parametrize("case", ["unknown", "unowned", "failed", "missing"])
def test_reconstruction_rejects_unavailable_upload_before_creating_records(
    tus_api: tuple[TestClient, UUID, Path],
    new_building: bool,
    case: str,
) -> None:
    client, building_id, tus_dir = tus_api
    upload_id = uuid4().hex
    if case != "unknown":
        if case != "missing":
            _make_tus_upload(tus_dir, upload_id)
        _register_tus_upload(
            client,
            upload_id,
            status={
                "pending": UploadStatus.PENDING,
                "failed": UploadStatus.FAILED,
            }.get(case, UploadStatus.UPLOADED),
            user_id=uuid4() if case == "unowned" else USER_ID,
        )
    before = client.get("/buildings").json()
    url = (
        "/buildings/from-reconstruction/from-upload"
        if new_building
        else f"/buildings/{building_id}/reconstructions/from-upload"
    )
    response = client.post(url, json={"upload_id": upload_id})
    expected = {
        "unknown": 404,
        "unowned": 404,
        "pending": 409,
        "failed": 409,
        "missing": 503,
    }
    assert response.status_code == expected[case]
    assert client.get("/buildings").json() == before
    assert client.get(f"/buildings/{building_id}/reconstructions").json() == []


@pytest.mark.parametrize("upload_id", ["../escape", "a/b", "a" * 65, "", "not-a-uuid"])
def test_reconstruction_rejects_invalid_upload_id(
    tus_api: tuple[TestClient, UUID, Path],
    upload_id: str,
) -> None:
    client, building_id, _ = tus_api
    response = client.post(
        f"/buildings/{building_id}/reconstructions/from-upload",
        json={"upload_id": upload_id},
    )
    assert response.status_code == 422


def test_from_upload_building_from_reconstruction_creates_linked_records(
    tus_api: tuple[TestClient, UUID, Path],
) -> None:
    client, _, tus_dir = tus_api
    upload_id = uuid4().hex
    _make_tus_upload(tus_dir, upload_id)
    _register_tus_upload(client, upload_id)

    response = client.post(
        "/buildings/from-reconstruction/from-upload",
        json={
            "upload_id": upload_id,
            "building": {"name": "New hall"},
            "settings": {},
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["building"]["name"] == "New hall"
    assert body["building"]["user_id"] == str(USER_ID)
    assert body["reconstruction"]["building_id"] == body["building"]["id"]
    assert body["reconstruction"]["status"] == "scheduled"


def test_from_upload_submission_waits_for_incomplete_upload(
    tus_api: tuple[TestClient, UUID, Path],
) -> None:
    client, building_id, tus_dir = tus_api
    upload_id = uuid4().hex
    _make_tus_upload(tus_dir, upload_id, size=len(b"video bytes") + 5)
    _register_tus_upload(client, upload_id, status=UploadStatus.PENDING)

    response = client.post(
        f"/buildings/{building_id}/reconstructions/from-upload",
        json={"upload_id": upload_id, "settings": {}},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "waiting_for_upload"
    assert response.json()["prefect_workflow_id"] is None
    assert client.get(f"/buildings/{building_id}/reconstructions").json() == [
        response.json()
    ]


def test_from_upload_submission_maps_scheduling_failure_to_503(
    monkeypatch: pytest.MonkeyPatch,
    tus_api: tuple[TestClient, UUID, Path],
) -> None:
    client, building_id, tus_dir = tus_api
    upload_id = uuid4().hex
    _make_tus_upload(tus_dir, upload_id)
    _register_tus_upload(client, upload_id)

    async def fail_schedule(**kwargs: object) -> UUID:
        raise RuntimeError("Prefect unavailable")

    monkeypatch.setattr(
        splat_workflow, "schedule_splat_generation_from_tus", fail_schedule
    )

    response = client.post(
        f"/buildings/{building_id}/reconstructions/from-upload",
        json={"upload_id": upload_id, "settings": {}},
    )

    assert response.status_code == 503
    reconstruction_id = response.json()["detail"]["reconstruction_id"]
    listed = client.get(f"/buildings/{building_id}/reconstructions").json()
    assert listed[0]["id"] == reconstruction_id
    assert listed[0]["status"] == "failed"
    assert listed[0]["error_message"] == "RuntimeError: Prefect unavailable"


def _fake_flow_logger(monkeypatch: pytest.MonkeyPatch, module: object) -> None:
    class FakeRunLogger:
        def info(self, *args: object) -> None:
            pass

    monkeypatch.setattr(module, "get_run_logger", lambda: FakeRunLogger())


def test_copy_video_from_tus_upload_preserves_original(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_flow_logger(monkeypatch, splat_workflow)
    tus_dir = tmp_path / "tus"
    tus_dir.mkdir()
    upload_id = uuid4().hex
    binary = tus_dir / upload_id
    binary.write_bytes(b"video bytes")
    (tus_dir / f"{upload_id}.info").write_text("{}")
    video_path = tmp_path / "workflows" / upload_id / "video" / "input.mp4"

    result = asyncio.run(
        splat_workflow.copy_video_from_tus_upload.fn(
            tus_upload_path=str(binary),
            tus_video_filename="scan.mp4",
            video_path=str(video_path),
        )
    )

    assert result == str(video_path)
    assert video_path.read_bytes() == b"video bytes"
    assert binary.read_bytes() == b"video bytes"
    assert (tus_dir / f"{upload_id}.info").exists()
    assert not video_path.with_name("input.mp4.tmp").exists()


def test_copy_video_from_tus_upload_fails_on_missing_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_flow_logger(monkeypatch, splat_workflow)
    destination = tmp_path / "video" / "input.mp4"

    with pytest.raises(FileNotFoundError):
        asyncio.run(
            splat_workflow.copy_video_from_tus_upload.fn(
                tus_upload_path=str(tmp_path / "missing"),
                tus_video_filename="scan.mp4",
                video_path=str(destination),
            )
        )

    assert not destination.exists()
    assert not destination.with_name("input.mp4.tmp").exists()


def test_remove_expired_uploads_deletes_old_pairs_and_orphans(
    tmp_path: Path,
) -> None:
    upload_dir = tmp_path / "tus"
    upload_dir.mkdir()
    old = time.time() - 8 * 24 * 60 * 60
    recent = time.time()

    old_binary = _make_tus_upload(upload_dir, "oldupload")
    os.utime(old_binary, (old, old))
    os.utime(upload_dir / "oldupload.info", (old, old))
    fresh_binary = _make_tus_upload(upload_dir, "freshupload")
    os.utime(fresh_binary, (recent, recent))
    os.utime(upload_dir / "freshupload.info", (recent, recent))
    old_orphan = upload_dir / "oldorphan"
    old_orphan.write_bytes(b"chunk")
    os.utime(old_orphan, (old, old))
    fresh_orphan = upload_dir / "freshorphan"
    fresh_orphan.write_bytes(b"chunk")
    os.utime(fresh_orphan, (recent, recent))

    removed = tus_cleanup.remove_expired_uploads(upload_dir, retention_days=7)

    assert sorted(removed) == ["oldorphan", "oldupload"]
    assert not old_binary.exists()
    assert not (upload_dir / "oldupload.info").exists()
    assert not old_orphan.exists()
    assert fresh_binary.exists()
    assert (upload_dir / "freshupload.info").exists()
    assert fresh_orphan.exists()


def test_remove_expired_uploads_keeps_recently_touched_binaries(
    tmp_path: Path,
) -> None:
    upload_dir = tmp_path / "tus"
    upload_dir.mkdir()
    old = time.time() - 8 * 24 * 60 * 60
    recent = time.time()

    copied_binary = _make_tus_upload(upload_dir, "copiedupload")
    os.utime(copied_binary, (recent, recent))
    os.utime(upload_dir / "copiedupload.info", (old, old))

    removed = tus_cleanup.remove_expired_uploads(upload_dir, retention_days=7)

    assert removed == []
    assert copied_binary.exists()
    assert (upload_dir / "copiedupload.info").exists()


def test_tus_cleanup_flow_uses_configured_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_flow_logger(monkeypatch, tus_cleanup)
    upload_dir = tmp_path / "tus"
    upload_dir.mkdir()
    monkeypatch.setattr(config, "TUSD_UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(config, "TUSD_UPLOAD_RETENTION_DAYS", 0)
    _make_tus_upload(upload_dir, "expired")
    expired = time.time() - 2 * 24 * 60 * 60
    os.utime(upload_dir / "expired", (expired, expired))
    os.utime(upload_dir / "expired.info", (expired, expired))

    removed = tus_cleanup.tus_cleanup_flow.fn()

    assert removed == ["expired"]
    assert not (upload_dir / "expired").exists()


def test_pre_finish_marks_uploaded_before_acknowledging(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
) -> None:
    monkeypatch.setattr(tus_views, "authenticate_user", _accept_any_token([]))
    creation = _hook_payload()
    assert tus_hook_api.post("/tus/hooks", json=creation).status_code == 200
    staging = _make_tus_upload(Path(config.TUSD_UPLOAD_DIR), UPLOAD_ID.hex)
    completion = _hook_payload(hook_type="pre-finish", headers={})
    response = tus_hook_api.post("/tus/hooks", json=completion)
    assert response.status_code == 200
    assert response.json() == {}
    uploaded = _read_hook_upload(tus_hook_api)
    assert uploaded is not None
    assert uploaded.status == UploadStatus.UPLOADED
    assert uploaded.uploaded_bytes == uploaded.size_bytes
    assert uploaded.uploaded_at is not None
    assert uploaded.file_path == str(upload_file_path(UPLOAD_ID, "scan.mp4"))
    assert Path(uploaded.file_path).read_bytes() == b"video bytes"
    assert not staging.exists()
    assert not staging.with_name(staging.name + ".info").exists()
    assert tus_hook_api.post("/tus/hooks", json=completion).status_code == 200
    assert tus_hook_api.post("/tus/hooks", json=creation).status_code == 200
    assert _read_hook_upload(tus_hook_api) == uploaded


@pytest.mark.parametrize(
    "changes",
    [
        {"Offset": 5},
        {"Size": 12, "Offset": 12},
        {"MetaData": {"filename": "different.mp4"}},
    ],
)
def test_pre_finish_rejects_mismatched_completion(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
    changes: dict[str, object],
) -> None:
    monkeypatch.setattr(tus_views, "authenticate_user", _accept_any_token([]))
    assert tus_hook_api.post("/tus/hooks", json=_hook_payload()).status_code == 200
    before = _read_hook_upload(tus_hook_api)
    payload = _hook_payload(hook_type="pre-finish")
    payload["Event"]["Upload"].update(changes)
    response = tus_hook_api.post("/tus/hooks", json=payload)
    assert response.status_code == 409
    assert _read_hook_upload(tus_hook_api) == before


def test_pre_finish_rejects_unregistered_upload(tus_hook_api: TestClient) -> None:
    response = tus_hook_api.post(
        "/tus/hooks",
        json=_hook_payload(hook_type="pre-finish"),
    )
    assert response.status_code == 404
    assert _read_hook_upload(tus_hook_api) is None


@pytest.mark.parametrize("secret", ["", "incorrect"])
@pytest.mark.parametrize("hook_type", ["pre-create", "post-receive"])
def test_hook_rejects_invalid_internal_credential(
    tus_hook_api: TestClient,
    secret: str,
    hook_type: str,
) -> None:
    response = tus_hook_api.post(
        "/tus/hooks",
        json=_hook_payload(hook_type=hook_type),
        headers={TUS_HOOK_SECRET_HEADER: secret},
    )
    assert response.status_code == 403
    assert _read_hook_upload(tus_hook_api) is None


def test_hook_requires_configured_secret(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
) -> None:
    monkeypatch.setattr(config, "TUSD_HOOK_SECRET", "")
    assert tus_hook_api.post("/tus/hooks", json=_hook_payload()).status_code == 503
    assert _read_hook_upload(tus_hook_api) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"Size": True},
        {"Size": -1},
        {"Size": 2**63},
        {"Offset": True},
        {"Offset": -1},
        {"Offset": 12},
        {"IsPartial": True},
        {"IsFinal": True},
        {"PartialUploads": ["another-upload"]},
    ],
)
def test_creation_rejects_invalid_sizes_offsets_and_concatenation(
    tus_hook_api: TestClient,
    changes: dict[str, object],
) -> None:
    payload = _hook_payload()
    payload["Event"]["Upload"].update(changes)
    response = tus_hook_api.post("/tus/hooks", json=payload)
    assert response.status_code == 200
    assert response.json()["RejectUpload"] is True
    assert response.json()["HTTPResponse"]["StatusCode"] == 400
    assert _read_hook_upload(tus_hook_api) is None


def test_creation_requires_proxy_generated_id(tus_hook_api: TestClient) -> None:
    payload = _hook_payload()
    del payload["Event"]["HTTPRequest"]["Header"][TUS_UPLOAD_ID_HEADER]
    response = tus_hook_api.post("/tus/hooks", json=payload)
    assert response.status_code == 200
    assert response.json()["HTTPResponse"]["StatusCode"] == 400
    assert _read_hook_upload(tus_hook_api) is None


def test_creation_rejects_conflicting_registration(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
) -> None:
    monkeypatch.setattr(tus_views, "authenticate_user", _accept_any_token([]))
    assert tus_hook_api.post("/tus/hooks", json=_hook_payload()).status_code == 200
    response = tus_hook_api.post("/tus/hooks", json=_hook_payload(size=12))
    assert response.status_code == 200
    assert response.json()["HTTPResponse"]["StatusCode"] == 409
    upload = _read_hook_upload(tus_hook_api)
    assert upload is not None
    assert upload.size_bytes == 11


@pytest.mark.parametrize("operation", ["create", "update_progress", "complete"])
def test_hook_database_failures_are_retryable(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
    operation: str,
) -> None:
    monkeypatch.setattr(tus_views, "authenticate_user", _accept_any_token([]))
    if operation != "create":
        assert tus_hook_api.post("/tus/hooks", json=_hook_payload()).status_code == 200
    if operation == "complete":
        _make_tus_upload(Path(config.TUSD_UPLOAD_DIR), UPLOAD_ID.hex)
    payload = _hook_payload(
        hook_type={
            "create": "pre-create",
            "update_progress": "post-receive",
            "complete": "pre-finish",
        }[operation],
        offset=5 if operation == "update_progress" else None,
    )
    with monkeypatch.context() as patches:
        patches.setattr(
            UserUploadsService,
            operation,
            AsyncMock(side_effect=OSError("database unavailable")),
        )
        response = tus_hook_api.post("/tus/hooks", json=payload)
    assert response.status_code == 500
    upload = _read_hook_upload(tus_hook_api)
    assert upload is None or upload.status == UploadStatus.PENDING
    assert tus_hook_api.post("/tus/hooks", json=payload).status_code == 200


def test_post_receive_records_progress_without_completing(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
) -> None:
    monkeypatch.setattr(tus_views, "authenticate_user", _accept_any_token([]))
    assert tus_hook_api.post("/tus/hooks", json=_hook_payload()).status_code == 200
    for offset, expected in [(5, 5), (5, 5), (3, 5), (11, 11)]:
        response = tus_hook_api.post(
            "/tus/hooks",
            json=_hook_payload(hook_type="post-receive", offset=offset, headers={}),
        )
        assert response.status_code == 200
        assert response.json() == {}
        upload = _read_hook_upload(tus_hook_api)
        assert upload is not None
        assert upload.uploaded_bytes == expected
        assert upload.status == UploadStatus.PENDING
        assert upload.uploaded_at is None

    _make_tus_upload(Path(config.TUSD_UPLOAD_DIR), UPLOAD_ID.hex)
    assert (
        tus_hook_api.post(
            "/tus/hooks", json=_hook_payload(hook_type="pre-finish", headers={})
        ).status_code
        == 200
    )
    completed = _read_hook_upload(tus_hook_api)
    assert (
        tus_hook_api.post(
            "/tus/hooks",
            json=_hook_payload(hook_type="post-receive", offset=5, headers={}),
        ).status_code
        == 200
    )
    assert _read_hook_upload(tus_hook_api) == completed


@pytest.mark.parametrize(
    ("changes", "expected_status"),
    [
        ({"Offset": -1}, 400),
        ({"Offset": 12}, 400),
        ({"Offset": True}, 400),
        ({"Size": 12}, 409),
        ({"MetaData": {"filename": "other.mp4"}}, 409),
    ],
)
def test_post_receive_rejects_invalid_or_mismatched_progress(
    monkeypatch: pytest.MonkeyPatch,
    tus_hook_api: TestClient,
    changes: dict[str, object],
    expected_status: int,
) -> None:
    monkeypatch.setattr(tus_views, "authenticate_user", _accept_any_token([]))
    assert tus_hook_api.post("/tus/hooks", json=_hook_payload()).status_code == 200
    before = _read_hook_upload(tus_hook_api)
    payload = _hook_payload(hook_type="post-receive", offset=5)
    payload["Event"]["Upload"].update(changes)
    response = tus_hook_api.post("/tus/hooks", json=payload)
    assert response.status_code == expected_status
    assert _read_hook_upload(tus_hook_api) == before


def test_post_receive_rejects_unregistered_upload(tus_hook_api: TestClient) -> None:
    response = tus_hook_api.post(
        "/tus/hooks", json=_hook_payload(hook_type="post-receive", offset=5)
    )
    assert response.status_code == 404
    assert _read_hook_upload(tus_hook_api) is None


def test_remove_staging_upload_deletes_pair_inside_staging_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    upload_dir = tmp_path / "tus"
    upload_dir.mkdir()
    monkeypatch.setattr(config, "TUSD_UPLOAD_DIR", str(upload_dir))
    binary = _make_tus_upload(upload_dir, "stagedupload")

    assert tus_cleanup.remove_staging_upload(str(binary)) is True
    assert not binary.exists()
    assert not (upload_dir / "stagedupload.info").exists()


def test_remove_staging_upload_rejects_paths_outside_staging_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    upload_dir = tmp_path / "tus"
    upload_dir.mkdir()
    monkeypatch.setattr(config, "TUSD_UPLOAD_DIR", str(upload_dir))
    outside = tmp_path / "elsewhere.video"
    outside.write_bytes(b"chunk")

    assert tus_cleanup.remove_staging_upload(str(outside)) is False
    assert outside.exists()
    assert tus_cleanup.remove_staging_upload(str(upload_dir / "missing")) is False
