"""Opt-in tests against an isolated real tusd container.

Set HUD_TEST_TUS_INTEGRATION=1 to run. HUD_TEST_UPLOAD_DB_URL can point at a
throwaway PostgreSQL database to exercise concurrent hook delivery and row locks.
The tests create and stop their own container; existing tusd containers are untouched.
"""

import asyncio
import base64
import os
import secrets
import socket
import subprocess
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from api.config import config
from api.db import get_session
from api.lib.tus import TUS_HOOK_SECRET_HEADER, TUS_UPLOAD_ID_HEADER
from api.lib.upload_storage import upload_file_path
from api.lib.workflows import common as workflow_common
from api.lib.workflows import splat_generation as splat_workflow
from api.main import app
from api.models.auth import AuthenticatedUser
from api.models.reconstruction import Reconstruction, ReconstructionStatus
from api.models.user import User
from api.services import auth as auth_service
from api.services import uploads as upload_service
from api.services.uploads import UserUploadsService
from api.views import tus as tus_views
from api.views.tus_proxy import close_tus_proxy

pytestmark = pytest.mark.skipif(
    os.environ.get("HUD_TEST_TUS_INTEGRATION") != "1",
    reason="Set HUD_TEST_TUS_INTEGRATION=1 to run the Docker integration tests",
)


@dataclass
class TusIntegration:
    client: httpx.Client
    hook_secret: str
    upload_directory: Path
    database_url: str


@pytest.fixture
def real_tus(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[TusIntegration]:
    upload_directory = tmp_path / "uploads"
    upload_directory.mkdir()
    database_url = os.environ.get(
        "HUD_TEST_UPLOAD_DB_URL",
        f"sqlite+aiosqlite:///{tmp_path / 'uploads.sqlite'}",
    )
    engine = create_async_engine(database_url)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(connection: Any, _: Any) -> None:
            connection.execute("PRAGMA foreign_keys=ON")

    hook_secret = secrets.token_hex(32)
    subject_prefix = f"tus-integration-{uuid4().hex}"
    subjects = [f"{subject_prefix}-owner", f"{subject_prefix}-other"]
    bearer = HTTPBearer(auto_error=False)

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> AuthenticatedUser:
        if credentials is None:
            raise HTTPException(401, "Missing bearer token")
        if credentials.credentials == "owner-token":
            return AuthenticatedUser(sub=subjects[0])
        if credentials.credentials == "other-token":
            return AuthenticatedUser(sub=subjects[1])
        raise HTTPException(401, "Invalid token")

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # The default database is a private SQLite file. A supplied PostgreSQL
        # database must already be migrated; do not alter its schema here.
        if database_url.startswith("sqlite"):
            from sqlmodel import SQLModel

            async with engine.begin() as connection:
                await connection.run_sync(SQLModel.metadata.create_all)
        try:
            yield
        finally:
            await close_tus_proxy()
            await engine.dispose()

    overrides: dict[Callable[..., Any], Callable[..., Any]] = dict(
        app.dependency_overrides
    )
    overrides[get_session] = session_override
    overrides[auth_service.authenticate_user] = authenticate
    monkeypatch.setattr(app, "dependency_overrides", overrides)
    monkeypatch.setattr(tus_views, "authenticate_user", authenticate)
    monkeypatch.setattr(app.router, "lifespan_context", lifespan)
    monkeypatch.setattr(config, "TUSD_HOOK_SECRET", hook_secret)
    monkeypatch.setattr(config, "TUSD_UPLOAD_DIR", str(upload_directory))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        workflow_common, "WORKFLOW_DATA_DIRECTORY", config.DATA_PATH / "workflows"
    )

    api_socket = socket.socket()
    api_socket.bind(("0.0.0.0", 0))
    api_port = api_socket.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=5)
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [api_socket]},
        daemon=True,
    )
    container_name = f"hud-tus-test-{uuid4().hex}"
    container_started = False
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            assert thread.is_alive(), "Integration API exited during startup"
            assert time.monotonic() < deadline, "Integration API did not start"
            time.sleep(0.01)

        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-d",
                "--name",
                container_name,
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--publish",
                "127.0.0.1::8080",
                "--add-host",
                "host.docker.internal:host-gateway",
                "--volume",
                f"{upload_directory.resolve()}:/data",
                "tusproject/tusd:v2.10.1",
                "-upload-dir=/data",
                "-port=8080",
                f"-hooks-http=http://host.docker.internal:{api_port}/tus/hooks",
                "-hooks-enabled-events=pre-create,post-receive,pre-finish",
                "-progress-hooks-interval=100ms",
                "-hooks-http-timeout=1800s",
                "-network-timeout=1860s",
                f"-hooks-http-forward-headers={TUS_HOOK_SECRET_HEADER}",
                "-disable-concatenation",
                "-disable-download",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        container_started = True
        published = subprocess.run(
            ["docker", "port", container_name, "8080/tcp"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        tus_port = int(published.rsplit(":", 1)[1])
        monkeypatch.setattr(config, "TUSD_INTERNAL_URL", f"http://127.0.0.1:{tus_port}")
        with httpx.Client(
            base_url=f"http://127.0.0.1:{api_port}",
            headers={"Authorization": "Bearer owner-token", "Tus-Resumable": "1.0.0"},
            timeout=30,
        ) as client:
            deadline = time.monotonic() + 15
            while client.options("/tus/files/").status_code not in (200, 204):
                assert time.monotonic() < deadline, "tusd did not start"
                time.sleep(0.1)
            for token in ("owner-token", "other-token"):
                accepted = client.post(
                    "/terms/accept", headers={"Authorization": f"Bearer {token}"}
                )
                assert accepted.status_code == 200, accepted.text
            yield TusIntegration(client, hook_secret, upload_directory, database_url)
    finally:
        if container_started:
            subprocess.run(
                ["docker", "stop", "--time", "1", container_name],
                check=False,
                capture_output=True,
                timeout=15,
            )
        server.should_exit = True
        thread.join(timeout=15)
        api_socket.close()
        assert not thread.is_alive(), "Integration API did not stop"

        if database_url.startswith("postgresql"):

            async def cleanup() -> None:
                async with AsyncSession(engine) as session:
                    await session.exec(
                        delete(User).where(col(User.keycloak_sub).in_(subjects))
                    )
                    await session.commit()
                await engine.dispose()

            asyncio.run(cleanup())


def _start_upload(real_tus: TusIntegration) -> tuple[str, str]:
    metadata = base64.b64encode(b"scan.mp4").decode("ascii")
    response = real_tus.client.post(
        "/tus/files/",
        headers={
            "Upload-Length": "11",
            "Upload-Metadata": f"filename {metadata}",
            TUS_UPLOAD_ID_HEADER: "client-cannot-choose-id",
            TUS_HOOK_SECRET_HEADER: "client-cannot-choose-secret",
        },
    )
    assert response.status_code == 201, response.text
    location = response.headers["Location"]
    upload_id = location.rsplit("/", 1)[1]
    return location, upload_id


def test_real_tus_registration_resume_completion_and_delete(
    real_tus: TusIntegration,
) -> None:
    client = real_tus.client
    location, upload_id = _start_upload(real_tus)
    record = client.get(f"/uploads/{upload_id}").json()
    assert record["id"].replace("-", "") == upload_id
    assert record["name"] == "TODO"
    assert record["description"] == ""
    assert record["filename"] == "scan.mp4"
    assert record["size_bytes"] == 11
    assert "file_path" not in record
    assert record["status"] == "pending"
    assert record["uploaded_bytes"] == 0
    assert record["uploaded_at"] is None
    assert client.post("/uploads", json={}).status_code == 405

    partial = client.patch(
        location,
        headers={
            "Content-Type": "application/offset+octet-stream",
            "Upload-Offset": "0",
        },
        content=b"video",
    )
    assert partial.status_code == 204, partial.text
    assert partial.headers["Upload-Offset"] == "5"
    for path in [location, f"/uploads/{upload_id}"]:
        assert client.delete(path).status_code == 409
    assert (real_tus.upload_directory / upload_id).read_bytes() == b"video"
    assert client.head(location).headers["Upload-Offset"] == "5"
    assert client.get(f"/uploads/{upload_id}").json()["status"] == "pending"
    for method in ["HEAD", "PATCH", "DELETE"]:
        response = client.request(
            method, location, headers={"Authorization": "Bearer other-token"}
        )
        assert response.status_code == 404

    completed = client.patch(
        location,
        headers={
            "Content-Type": "application/offset+octet-stream",
            "Upload-Offset": "5",
        },
        content=b" bytes",
    )
    assert completed.status_code == 204, completed.text
    uploaded = client.get(f"/uploads/{upload_id}").json()
    assert uploaded["status"] == "uploaded"
    assert uploaded["uploaded_bytes"] == 11
    assert uploaded["uploaded_at"] is not None
    stored = upload_file_path(UUID(upload_id), "scan.mp4")
    assert stored.read_bytes() == b"video bytes"
    assert not (real_tus.upload_directory / upload_id).exists()
    assert not (real_tus.upload_directory / f"{upload_id}.info").exists()
    assert client.head(location).headers["Upload-Offset"] == "11"
    assert (
        client.get(f"/uploads/{upload_id}").json()["uploaded_at"]
        == uploaded["uploaded_at"]
    )
    empty_retry = client.patch(
        location,
        headers={
            "Content-Type": "application/offset+octet-stream",
            "Upload-Offset": "11",
        },
        content=b"",
    )
    assert empty_retry.status_code == 204
    assert empty_retry.headers["Upload-Offset"] == "11"
    assert (
        client.patch(
            location,
            headers={
                "Content-Type": "application/offset+octet-stream",
                "Upload-Offset": "11",
            },
            content=b"extra",
        ).status_code
        == 409
    )
    assert client.delete(location).status_code == 204
    assert not (real_tus.upload_directory / upload_id).exists()
    assert not (real_tus.upload_directory / f"{upload_id}.info").exists()
    assert stored.read_bytes() == b"video bytes"
    assert client.delete(f"/uploads/{upload_id}").status_code == 204
    assert stored.read_bytes() == b"video bytes"


def test_real_tus_reports_progress_before_patch_finishes(
    real_tus: TusIntegration,
) -> None:
    client = real_tus.client
    location, upload_id = _start_upload(real_tus)
    finish_transfer = threading.Event()

    def body() -> Iterator[bytes]:
        yield b"video"
        if not finish_transfer.wait(timeout=10):
            raise AssertionError("Progress was not observed during the PATCH")
        yield b" bytes"

    def transfer() -> httpx.Response:
        return client.patch(
            location,
            headers={
                "Content-Type": "application/offset+octet-stream",
                "Upload-Offset": "0",
            },
            content=body(),
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(transfer)
        try:
            deadline = time.monotonic() + 5
            while True:
                record = client.get(f"/uploads/{upload_id}").json()
                if record["uploaded_bytes"] == 5:
                    break
                assert time.monotonic() < deadline, record
                assert not pending.done()
                time.sleep(0.05)
            assert not pending.done()
            assert record["status"] == "pending"
            assert record["uploaded_at"] is None
            listed = client.get("/uploads").json()
            assert (
                next(row for row in listed if row["id"] == record["id"])[
                    "uploaded_bytes"
                ]
                == 5
            )
        finally:
            finish_transfer.set()
        response = pending.result(timeout=10)
    assert response.status_code == 204, response.text
    completed = client.get(f"/uploads/{upload_id}").json()
    assert completed["uploaded_bytes"] == completed["size_bytes"] == 11
    assert completed["status"] == "uploaded"


def test_real_tus_upload_is_reusable_for_both_reconstruction_routes(
    monkeypatch: pytest.MonkeyPatch,
    real_tus: TusIntegration,
) -> None:
    scheduled: list[dict[str, Any]] = []

    async def schedule(**kwargs: Any) -> UUID:
        scheduled.append(kwargs)
        return uuid4()

    monkeypatch.setattr(splat_workflow, "schedule_splat_generation_from_tus", schedule)
    client = real_tus.client
    location, upload_id = _start_upload(real_tus)
    first = client.post(
        "/buildings/from-reconstruction/from-upload",
        json={"upload_id": upload_id},
    )
    assert first.status_code == 202, first.text
    assert first.json()["reconstruction"]["status"] == "waiting_for_upload"
    assert scheduled == []
    response = client.patch(
        location,
        headers={
            "Content-Type": "application/offset+octet-stream",
            "Upload-Offset": "0",
        },
        content=b"video bytes",
    )
    assert response.status_code == 204
    building_id = first.json()["building"]["id"]
    second = client.post(
        f"/buildings/{building_id}/reconstructions/from-upload",
        json={"upload_id": upload_id},
    )
    assert second.status_code == 202, second.text
    source = upload_file_path(UUID(upload_id), "scan.mp4")
    assert len(scheduled) == 2
    for parameters in scheduled:
        assert parameters["tus_upload_path"] == str(source)
        artifact = parameters["artifact"]
        splat_workflow._copy_tus_upload(
            str(source), "scan.mp4", str(artifact.video_path)
        )
        assert artifact.video_path.read_bytes() == b"video bytes"
        assert source.read_bytes() == b"video bytes"
    assert not (real_tus.upload_directory / upload_id).exists()
    assert client.delete(f"/uploads/{upload_id}").status_code == 204
    assert source.read_bytes() == b"video bytes"
    rows = client.get(f"/buildings/{building_id}/reconstructions").json()
    assert len(rows) == 2
    assert all(row["upload_id"] is None for row in rows)


@pytest.mark.parametrize("pause_after_commit", [False, True])
def test_submission_racing_completion_never_misses_or_duplicates_scheduling(
    monkeypatch: pytest.MonkeyPatch,
    real_tus: TusIntegration,
    pause_after_commit: bool,
) -> None:
    if not real_tus.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL is required to verify concurrent transactions")
    client = real_tus.client
    location, upload_id = _start_upload(real_tus)
    paused = threading.Event()
    resume = threading.Event()
    original_commit = AsyncSession.commit
    scheduled: list[dict[str, Any]] = []

    async def commit_with_pause(session: AsyncSession) -> None:
        creating = any(
            isinstance(row, Reconstruction)
            and row.status == ReconstructionStatus.WAITING_FOR_UPLOAD
            for row in session.new
        )
        if not creating:
            await original_commit(session)
            return
        if pause_after_commit:
            await original_commit(session)
        paused.set()
        assert await asyncio.to_thread(resume.wait, 15), "Creation was not resumed"
        if not pause_after_commit:
            await original_commit(session)

    async def schedule(**kwargs: Any) -> UUID:
        scheduled.append(kwargs)
        return uuid4()

    monkeypatch.setattr(AsyncSession, "commit", commit_with_pause)
    monkeypatch.setattr(splat_workflow, "schedule_splat_generation_from_tus", schedule)
    with ThreadPoolExecutor(max_workers=2) as executor:
        creation = executor.submit(
            client.post,
            "/buildings/from-reconstruction/from-upload",
            json={"upload_id": upload_id, "settings": {"ffmpeg": {"fps": 4}}},
        )
        try:
            assert paused.wait(10), "Creation did not reach the commit boundary"
            completion = executor.submit(
                client.patch,
                location,
                headers={
                    "Content-Type": "application/offset+octet-stream",
                    "Upload-Offset": "0",
                },
                content=b"video bytes",
            )
            if pause_after_commit:
                completed = completion.result(timeout=15)
                assert completed.status_code == 204, completed.text
                assert len(scheduled) == 1
        finally:
            resume.set()
        result = creation.result(timeout=15)
        completed = completion.result(timeout=15)
        assert completed.status_code == 204, completed.text
    assert result.status_code == 202, result.text
    row = result.json()["reconstruction"]
    saved = client.get(
        f"/buildings/{row['building_id']}/reconstructions/{row['id']}"
    ).json()
    assert saved["status"] == "scheduled"
    assert len(scheduled) == 1
    assert str(scheduled[0]["reconstruction_id"]) == row["id"]
    assert scheduled[0]["settings"].ffmpeg.fps == 4


def test_real_tus_recovers_failed_pre_finish(
    monkeypatch: pytest.MonkeyPatch,
    real_tus: TusIntegration,
) -> None:
    location, upload_id = _start_upload(real_tus)

    async def fail_completion(self: UserUploadsService, upload_id: object) -> None:
        raise OSError("simulated database outage")

    with monkeypatch.context() as patches:
        patches.setattr(UserUploadsService, "complete", fail_completion)
        failed = real_tus.client.patch(
            location,
            headers={
                "Content-Type": "application/offset+octet-stream",
                "Upload-Offset": "0",
            },
            content=b"video bytes",
        )
        assert failed.status_code == 500
        assert (
            real_tus.client.get(f"/uploads/{upload_id}").json()["status"] == "pending"
        )
        assert real_tus.client.head(location).status_code == 503
    assert real_tus.client.head(location).status_code == 200
    assert real_tus.client.get(f"/uploads/{upload_id}").json()["status"] == "uploaded"


def test_concurrent_hook_delivery_preserves_one_row_and_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    real_tus: TusIntegration,
) -> None:
    if not real_tus.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL is required to verify row locks")
    assert real_tus.client.get("/uploads").status_code == 200
    upload_id = uuid4().hex
    payload: dict[str, Any] = {
        "Type": "pre-create",
        "Event": {
            "Upload": {
                "ID": None,
                "Size": 11,
                "Offset": 0,
                "MetaData": {"filename": "scan.mp4"},
            },
            "HTTPRequest": {
                "Header": {
                    "Authorization": ["Bearer owner-token"],
                    TUS_UPLOAD_ID_HEADER: [upload_id],
                },
            },
        },
    }
    base_url = str(real_tus.client.base_url)
    headers = {TUS_HOOK_SECRET_HEADER: real_tus.hook_secret}

    async def deliver(events: list[dict[str, Any]]) -> list[httpx.Response]:
        async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
            return await asyncio.gather(
                *[
                    client.post("/tus/hooks", json=event, headers=headers)
                    for event in events
                ]
            )

    assert all(
        response.status_code == 200 for response in asyncio.run(deliver([payload] * 5))
    )
    assert len(real_tus.client.get("/uploads").json()) == 1
    scheduled: list[dict[str, Any]] = []

    async def schedule(**kwargs: Any) -> UUID:
        scheduled.append(kwargs)
        await asyncio.sleep(0.05)  # Keep the claim in flight during other deliveries.
        return uuid4()

    monkeypatch.setattr(splat_workflow, "schedule_splat_generation_from_tus", schedule)
    rows = []
    for fps in (3, 5):
        created = real_tus.client.post(
            "/buildings/from-reconstruction/from-upload",
            json={"upload_id": upload_id, "settings": {"ffmpeg": {"fps": fps}}},
        )
        assert created.status_code == 202, created.text
        rows.append(created.json()["reconstruction"])
    (real_tus.upload_directory / upload_id).write_bytes(b"video bytes")
    payload["Type"] = "pre-finish"
    payload["Event"]["Upload"]["ID"] = upload_id
    payload["Event"]["Upload"]["Offset"] = 11
    progress = deepcopy(payload)
    progress["Type"] = "post-receive"
    progress["Event"]["Upload"]["Offset"] = 5
    calls: list[datetime] = []

    def completion_time() -> datetime:
        timestamp = datetime.now(UTC)
        calls.append(timestamp)
        return timestamp

    monkeypatch.setattr(upload_service, "utc_now", completion_time)
    assert all(
        response.status_code == 200
        for response in asyncio.run(deliver([progress, payload] * 5))
    )
    assert len(calls) == 1
    uploaded = real_tus.client.get(f"/uploads/{upload_id}").json()
    assert uploaded["uploaded_bytes"] == uploaded["size_bytes"] == 11
    assert datetime.fromisoformat(uploaded["uploaded_at"]) == calls[0]
    assert len(scheduled) == 2
    assert {str(call["reconstruction_id"]) for call in scheduled} == {
        row["id"] for row in rows
    }
    for row in rows:
        saved = real_tus.client.get(
            f"/buildings/{row['building_id']}/reconstructions/{row['id']}"
        ).json()
        assert saved["status"] == "scheduled"
