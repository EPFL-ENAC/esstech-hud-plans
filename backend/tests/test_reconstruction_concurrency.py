"""Opt-in PostgreSQL races using independent sessions and observed lock waits.

Run with HUD_TEST_POSTGRES=1 and the local DB settings. Each test creates and
drops its own schema; existing application tables and data are untouched.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from api.config import config
from api.lib.workflows import common, splat_generation
from api.models.building import Building
from api.models.reconstruction import (
    Reconstruction,
    ReconstructionArtifactUpdate,
    ReconstructionStatus,
)
from api.models.uploads import UploadStatus, UserUploads
from api.models.user import User
from api.models.workflows import SplatGenerationWorkflowSettings
from api.services.buildings import BuildingService
from api.services.reconstructions import (
    ReconstructionInputNotFoundError,
    ReconstructionService,
)
from api.services.uploads import UploadConflictError, UserUploadsService

pytestmark = pytest.mark.skipif(
    os.environ.get("HUD_TEST_POSTGRES") != "1",
    reason="Set HUD_TEST_POSTGRES=1 to verify PostgreSQL concurrency",
)


@dataclass
class Database:
    engine: AsyncEngine
    user_id: UUID
    building_id: UUID
    upload_id: UUID
    reconstruction_id: UUID


@asynccontextmanager
async def database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    upload_status: UploadStatus = UploadStatus.UPLOADED,
) -> AsyncIterator[Database]:
    schema = f"reconstruction_test_{uuid4().hex}"
    admin = create_async_engine(config.DB_URL)
    engine = create_async_engine(
        config.DB_URL,
        connect_args={"server_settings": {"search_path": schema}},
    )
    state = Database(engine, uuid4(), uuid4(), uuid4(), uuid4())
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video bytes")
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "TUSD_UPLOAD_DIR", str(tmp_path / "tus"))
    monkeypatch.setattr(config, "USE_SCITAS", False)
    monkeypatch.setattr(common, "WORKFLOW_DATA_DIRECTORY", tmp_path / "workflows")
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(User(id=state.user_id, keycloak_sub=str(state.user_id)))
            await session.flush()
            session.add_all(
                [
                    Building(
                        id=state.building_id,
                        user_id=state.user_id,
                        name="Concurrency test",
                    ),
                    UserUploads(
                        id=state.upload_id,
                        user_id=state.user_id,
                        filename="video.mp4",
                        file_path=str(video),
                        size_bytes=video.stat().st_size,
                        status=upload_status,
                    ),
                ]
            )
            await session.flush()
            session.add(
                Reconstruction(
                    id=state.reconstruction_id,
                    building_id=state.building_id,
                    upload_id=state.upload_id,
                    status=ReconstructionStatus.WAITING_FOR_UPLOAD,
                    settings=SplatGenerationWorkflowSettings().model_dump(mode="json"),
                )
            )
            await session.commit()
        yield state
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def wait_for_lock(engine: AsyncEngine, pid: int) -> None:
    async with asyncio.timeout(5):
        while True:
            async with engine.connect() as connection:
                waiting = await connection.scalar(
                    text(
                        "SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid = :pid"
                    ),
                    {"pid": pid},
                )
            if waiting:
                return
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("action", ["cancel", "delete", "running", "complete"])
def test_registration_serializes_other_operations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            registering = asyncio.Event()
            release = asyncio.Event()
            workflow_id = uuid4()
            calls = []

            async def register(**kwargs):
                calls.append(kwargs)
                registering.set()
                await release.wait()
                return workflow_id

            monkeypatch.setattr(
                splat_generation, "schedule_splat_generation_from_upload", register
            )
            cancel = AsyncMock()
            monkeypatch.setattr(common, "cancel_workflow", cancel)

            async def complete() -> None:
                async with AsyncSession(
                    state.engine, expire_on_commit=False
                ) as session:
                    await UserUploadsService(session).complete(state.upload_id)

            registration = asyncio.create_task(complete())
            async with asyncio.timeout(5):
                await registering.wait()
            ready: asyncio.Future[int] = asyncio.Future()

            async def compete() -> None:
                async with AsyncSession(
                    state.engine, expire_on_commit=False
                ) as session:
                    ready.set_result(
                        await session.scalar(text("SELECT pg_backend_pid()"))
                    )
                    service = ReconstructionService(session)
                    if action == "complete":
                        await UserUploadsService(session).complete(state.upload_id)
                    elif action == "running":
                        await service.mark_running(
                            state.reconstruction_id,
                            prefect_workflow_id=workflow_id,
                        )
                    elif action == "cancel":
                        await service.cancel(state.reconstruction_id)
                    else:
                        await service.delete(state.reconstruction_id)

            competing = asyncio.create_task(compete())
            try:
                await wait_for_lock(state.engine, await ready)
            finally:
                release.set()
                await asyncio.wait_for(asyncio.gather(registration, competing), 5)

            assert len(calls) == 1
            async with AsyncSession(state.engine) as session:
                row = await session.get(Reconstruction, state.reconstruction_id)
                if action == "delete":
                    assert row is None
                else:
                    assert row is not None
                    assert row.prefect_workflow_id == workflow_id
                    assert (
                        row.status
                        == {
                            "cancel": ReconstructionStatus.CANCELLED,
                            "running": ReconstructionStatus.RUNNING,
                            "complete": ReconstructionStatus.SCHEDULED,
                        }[action]
                    )
            assert cancel.await_count == int(action in {"cancel", "delete"})

    asyncio.run(run())


def test_concurrent_progress_reloads_after_lock_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            locked = asyncio.Event()
            release = asyncio.Event()
            async with (
                AsyncSession(state.engine, expire_on_commit=False) as first,
                AsyncSession(state.engine, expire_on_commit=False) as second,
            ):
                service = ReconstructionService(first)
                original = service._get_for_update

                async def hold_lock(reconstruction_id):
                    row = await original(reconstruction_id)
                    locked.set()
                    await release.wait()
                    return row

                monkeypatch.setattr(service, "_get_for_update", hold_lock)
                # Preload stale state in the second session before the first write.
                stale = await second.get(Reconstruction, state.reconstruction_id)
                pid = await second.scalar(text("SELECT pg_backend_pid()"))
                high = asyncio.create_task(
                    service.record_progress(state.reconstruction_id, progress=0.8)
                )
                await locked.wait()
                low = asyncio.create_task(
                    ReconstructionService(second).record_progress(
                        state.reconstruction_id, progress=0.4
                    )
                )
                try:
                    await wait_for_lock(state.engine, pid)
                finally:
                    release.set()
                    await asyncio.wait_for(asyncio.gather(high, low), 5)
                assert stale.progress == 0.8

    asyncio.run(run())


@pytest.mark.parametrize("delete_parent", [False, True])
def test_creation_revalidates_after_parent_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    delete_parent: bool,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            async with AsyncSession(state.engine, expire_on_commit=False) as deleting:
                existing = await deleting.get(Reconstruction, state.reconstruction_id)
                await deleting.delete(existing)
                await deleting.commit()
                model = Building if delete_parent else UserUploads
                identifier = state.building_id if delete_parent else state.upload_id
                parent = await deleting.get(model, identifier, with_for_update=True)
                async with AsyncSession(
                    state.engine, expire_on_commit=False
                ) as creating:
                    pid = await creating.scalar(text("SELECT pg_backend_pid()"))
                    creation = asyncio.create_task(
                        ReconstructionService(creating).create_from_upload(
                            user_id=state.user_id,
                            building_id=state.building_id,
                            upload_id=state.upload_id,
                            settings=SplatGenerationWorkflowSettings(),
                        )
                    )
                    try:
                        await wait_for_lock(state.engine, pid)
                    finally:
                        if delete_parent:
                            await BuildingService(deleting).delete(parent)
                        else:
                            await UserUploadsService(deleting).delete(state.upload_id)
                    with pytest.raises(ReconstructionInputNotFoundError):
                        await asyncio.wait_for(creation, 5)

    asyncio.run(run())


def test_upload_delete_rejects_uncommitted_scheduling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            async with AsyncSession(state.engine, expire_on_commit=False) as scheduling:
                row = await scheduling.get(
                    Reconstruction, state.reconstruction_id, with_for_update=True
                )
                row.status = ReconstructionStatus.SCHEDULED
                await scheduling.flush()
                async with AsyncSession(
                    state.engine, expire_on_commit=False
                ) as deleting:
                    with pytest.raises(UploadConflictError, match="waiting"):
                        await UserUploadsService(deleting).delete(state.upload_id)
                await scheduling.rollback()

    asyncio.run(run())


@pytest.mark.parametrize("pause_after_commit", [False, True])
def test_creation_and_completion_never_miss_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pause_after_commit: bool,
) -> None:
    async def run() -> None:
        async with database(
            tmp_path, monkeypatch, upload_status=UploadStatus.PENDING
        ) as state:
            async with AsyncSession(state.engine) as session:
                existing = await session.get(Reconstruction, state.reconstruction_id)
                await session.delete(existing)
                await session.commit()

            registered = AsyncMock(return_value=uuid4())
            monkeypatch.setattr(
                splat_generation, "schedule_splat_generation_from_upload", registered
            )
            paused = asyncio.Event()
            release = asyncio.Event()
            async with (
                AsyncSession(state.engine, expire_on_commit=False) as creating,
                AsyncSession(state.engine, expire_on_commit=False) as completing,
            ):
                original_commit = creating.commit
                first_commit = True

                async def commit_with_pause():
                    nonlocal first_commit
                    if not first_commit:
                        await original_commit()
                        return
                    first_commit = False
                    if pause_after_commit:
                        await original_commit()
                    paused.set()
                    await release.wait()
                    if not pause_after_commit:
                        await original_commit()

                monkeypatch.setattr(creating, "commit", commit_with_pause)
                creation = asyncio.create_task(
                    ReconstructionService(creating).create_from_upload(
                        user_id=state.user_id,
                        building_id=state.building_id,
                        upload_id=state.upload_id,
                        settings=SplatGenerationWorkflowSettings(),
                    )
                )
                async with asyncio.timeout(5):
                    await paused.wait()
                pid = await completing.scalar(text("SELECT pg_backend_pid()"))
                completion = asyncio.create_task(
                    UserUploadsService(completing).complete(state.upload_id)
                )
                try:
                    if pause_after_commit:
                        await asyncio.wait_for(asyncio.shield(completion), 5)
                    else:
                        await wait_for_lock(state.engine, pid)
                finally:
                    release.set()
                    result, _ = await asyncio.wait_for(
                        asyncio.gather(creation, completion), 5
                    )
                assert result.status in {
                    ReconstructionStatus.WAITING_FOR_UPLOAD,
                    ReconstructionStatus.SCHEDULED,
                }
                async with AsyncSession(state.engine) as checking:
                    saved = await checking.get(Reconstruction, result.id)
                    assert saved.status == ReconstructionStatus.SCHEDULED
                registered.assert_awaited_once()

    asyncio.run(run())


def test_unchanged_and_rejected_updates_release_the_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            async with AsyncSession(state.engine, expire_on_commit=False) as session:
                service = ReconstructionService(session)
                await service.cancel(state.reconstruction_id)
                operations = [
                    lambda: service.cancel(state.reconstruction_id),
                    lambda: service.mark_running(
                        state.reconstruction_id, prefect_workflow_id=uuid4()
                    ),
                    lambda: service.mark_completed(
                        state.reconstruction_id,
                        artifacts=ReconstructionArtifactUpdate(),
                    ),
                    lambda: service.mark_failed(
                        state.reconstruction_id, error_message="late"
                    ),
                    lambda: service.mark_crashed(state.reconstruction_id),
                    lambda: service.mark_cancelled(state.reconstruction_id),
                    lambda: service.record_progress(
                        state.reconstruction_id, progress=0.5
                    ),
                ]
                for operation in operations:
                    await operation()
                    async with AsyncSession(state.engine) as other:
                        await other.get(
                            Reconstruction,
                            state.reconstruction_id,
                            with_for_update={"nowait": True},
                        )
                with pytest.raises(ValueError):
                    await service.record_progress(state.reconstruction_id, progress=2)
                async with AsyncSession(state.engine) as other:
                    await other.get(
                        Reconstruction,
                        state.reconstruction_id,
                        with_for_update={"nowait": True},
                    )

    asyncio.run(run())


def test_cancelled_registration_request_rolls_back_and_releases_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            registering = asyncio.Event()

            async def never_finishes(**kwargs):
                registering.set()
                await asyncio.Event().wait()

            monkeypatch.setattr(
                splat_generation,
                "schedule_splat_generation_from_upload",
                never_finishes,
            )
            async with AsyncSession(state.engine, expire_on_commit=False) as session:
                registration = asyncio.create_task(
                    ReconstructionService(session)._schedule_if_ready(
                        state.reconstruction_id
                    )
                )
                async with asyncio.timeout(5):
                    await registering.wait()
                registration.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await registration
                async with AsyncSession(state.engine, expire_on_commit=False) as other:
                    row = await other.get(
                        Reconstruction,
                        state.reconstruction_id,
                        with_for_update={"nowait": True},
                    )
                    assert row.status == ReconstructionStatus.WAITING_FOR_UPLOAD
                    assert row.prefect_workflow_id is None

    asyncio.run(run())
