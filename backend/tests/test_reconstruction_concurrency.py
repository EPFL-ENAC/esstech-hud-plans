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
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from api.config import config
from api.db import get_session
from api.lib.workflows import common, splat_generation
from api.models.building import Building, BuildingCreate
from api.models.idempotency import IdempotencyRecords, IdempotencyStatus
from api.models.reconstruction import (
    Reconstruction,
    ReconstructionArtifactUpdate,
    ReconstructionStatus,
)
from api.models.uploads import UploadStatus, UserUploads
from api.models.user import User
from api.models.workflows import SplatGenerationWorkflowSettings
from api.services.auth import require_user
from api.services.buildings import BuildingService
from api.services.idempotency import IdempotencyInProgressError, IdempotencyService
from api.services.reconstructions import (
    ReconstructionInputNotFoundError,
    ReconstructionService,
)
from api.services.uploads import UploadConflictError, UserUploadsService
from api.views import buildings as building_views
from api.views import reconstructions as reconstruction_views

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


async def submit_reconstruction(
    session: AsyncSession,
    *,
    user_id: UUID,
    building_id: UUID,
    upload_id: UUID,
    settings: SplatGenerationWorkflowSettings,
) -> Reconstruction:
    service = ReconstructionService(session)
    async with IdempotencyService(session).operation(
        owner_id=user_id,
        idempotency_key=str(uuid4()),
    ) as should_run:
        assert should_run
        reconstruction = await service.add_from_upload(
            user_id=user_id,
            building_id=building_id,
            upload_id=upload_id,
            settings=settings,
        )
    return await service.schedule_if_ready(reconstruction.id)


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
                            "cancel": ReconstructionStatus.CANCELLING,
                            "running": ReconstructionStatus.RUNNING,
                            "complete": ReconstructionStatus.SCHEDULED,
                        }[action]
                    )
            assert cancel.await_count == int(action in {"cancel", "delete"})

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["pending", "hook", "failure"])
def test_cancellation_is_committed_and_unlocks_before_external_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            async with AsyncSession(state.engine, expire_on_commit=False) as session:
                row = await session.get(Reconstruction, state.reconstruction_id)
                row.status = ReconstructionStatus.RUNNING
                row.prefect_workflow_id = uuid4()
                row.progress = 0.4
                await session.commit()
                entered = asyncio.Event()
                release = asyncio.Event()

                @asynccontextmanager
                async def hook_service():
                    async with AsyncSession(
                        state.engine, expire_on_commit=False
                    ) as hook_session:
                        yield ReconstructionService(hook_session)

                async def cancel_workflow(workflow_id: UUID) -> None:
                    entered.set()
                    await release.wait()
                    if outcome == "failure":
                        raise OSError("Prefect unavailable")
                    if outcome == "hook":
                        await splat_generation._reconstruction_cancelled_hook(
                            None,
                            SimpleNamespace(
                                id=workflow_id,
                                parameters={"reconstruction_id": str(row.id)},
                            ),
                            SimpleNamespace(message="Cancelled", name="Cancelling"),
                        )

                monkeypatch.setattr(common, "cancel_workflow", cancel_workflow)
                monkeypatch.setattr(
                    splat_generation, "_reconstruction_service", hook_service
                )
                cancelling = asyncio.create_task(
                    ReconstructionService(session).cancel(row.id)
                )
                try:
                    async with asyncio.timeout(5):
                        await entered.wait()
                        async with AsyncSession(
                            state.engine, expire_on_commit=False
                        ) as checking:
                            visible = await checking.get(
                                Reconstruction, row.id, with_for_update={"nowait": True}
                            )
                            assert visible.status == ReconstructionStatus.CANCELLING
                            await checking.commit()
                            other_service = ReconstructionService(checking)
                            await other_service.mark_running(
                                row.id, prefect_workflow_id=uuid4()
                            )
                            await other_service.record_progress(row.id, progress=0.9)
                            await other_service.mark_completed(
                                row.id,
                                artifacts=ReconstructionArtifactUpdate(
                                    splat_path="/late/splat.ply"
                                ),
                            )
                            await other_service.mark_failed(
                                row.id, error_message="Late failure"
                            )
                            await other_service.mark_crashed(row.id)
                            assert visible.status == ReconstructionStatus.CANCELLING
                            assert visible.progress == 0.4
                            assert visible.splat_path is None
                finally:
                    release.set()
                    if outcome == "failure":
                        with pytest.raises(OSError, match="Prefect unavailable"):
                            await asyncio.wait_for(cancelling, 5)
                    else:
                        result = await asyncio.wait_for(cancelling, 5)
                        assert result.status == (
                            ReconstructionStatus.CANCELLED
                            if outcome == "hook"
                            else ReconstructionStatus.CANCELLING
                        )
                async with AsyncSession(state.engine) as checking:
                    saved = await checking.get(Reconstruction, row.id)
                    assert saved.status == (
                        ReconstructionStatus.CANCELLED
                        if outcome == "hook"
                        else ReconstructionStatus.CANCELLING
                    )

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
                        submit_reconstruction(
                            creating,
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
                    submit_reconstruction(
                        creating,
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
                    ReconstructionService(session).schedule_if_ready(
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


def test_idempotent_acceptance_rejects_concurrent_requests_and_replays_after_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            key = str(uuid4())
            async with (
                AsyncSession(state.engine, expire_on_commit=False) as accepting,
                AsyncSession(state.engine, expire_on_commit=False) as competing,
            ):
                async with IdempotencyService(accepting).operation(
                    owner_id=state.user_id,
                    idempotency_key=key,
                ) as should_run:
                    assert should_run
                    record = await accepting.get(
                        IdempotencyRecords, (state.user_id, key)
                    )
                    assert record is not None
                    assert record.status == IdempotencyStatus.STARTED
                    building = await BuildingService(accepting).add(
                        user_id=state.user_id,
                        payload=BuildingCreate(name="Accepted atomically"),
                    )
                    reconstruction = await ReconstructionService(
                        accepting
                    ).add_from_upload(
                        user_id=state.user_id,
                        building_id=building.id,
                        upload_id=state.upload_id,
                        settings=SplatGenerationWorkflowSettings(),
                    )
                    # The competitor must fail immediately, rather than waiting
                    # for either the resource rows or the idempotency record.
                    async with asyncio.timeout(1):
                        with pytest.raises(IdempotencyInProgressError):
                            async with IdempotencyService(competing).operation(
                                owner_id=state.user_id,
                                idempotency_key=key,
                            ):
                                pytest.fail("Concurrent acceptance must not run")
                    assert await competing.get(Building, building.id) is None
                    assert (
                        await competing.get(IdempotencyRecords, (state.user_id, key))
                        is None
                    )

                async with IdempotencyService(competing).operation(
                    owner_id=state.user_id,
                    idempotency_key=key,
                ) as should_run:
                    assert not should_run
                saved = await competing.get(Reconstruction, reconstruction.id)
                assert saved is not None
                assert saved.building_id == building.id
                assert saved.status == ReconstructionStatus.WAITING_FOR_UPLOAD
                assert (
                    await competing.scalar(
                        text("SELECT status::text FROM idempotency_records")
                    )
                    == "completed"
                )

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_failed_acceptance_releases_lock_and_rolls_back_all_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            key = str(uuid4())
            staged = asyncio.Event()
            release = asyncio.Event()
            building_id = uuid4()

            async def accept() -> None:
                nonlocal building_id
                async with AsyncSession(
                    state.engine, expire_on_commit=False
                ) as session:
                    async with IdempotencyService(session).operation(
                        owner_id=state.user_id,
                        idempotency_key=key,
                    ) as should_run:
                        assert should_run
                        building = await BuildingService(session).add(
                            user_id=state.user_id,
                            payload=BuildingCreate(name="Must roll back"),
                        )
                        building_id = building.id
                        await ReconstructionService(session).add_from_upload(
                            user_id=state.user_id,
                            building_id=building.id,
                            upload_id=state.upload_id,
                            settings=SplatGenerationWorkflowSettings(),
                        )
                        staged.set()
                        await release.wait()
                        raise RuntimeError("Acceptance interrupted")

            acceptance = asyncio.create_task(accept())
            try:
                async with asyncio.timeout(5):
                    await staged.wait()
            finally:
                if cancel:
                    acceptance.cancel()
                else:
                    release.set()
            with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
                await asyncio.wait_for(acceptance, 5)

            async with AsyncSession(state.engine, expire_on_commit=False) as session:
                assert await session.get(Building, building_id) is None
                assert (
                    await session.get(IdempotencyRecords, (state.user_id, key)) is None
                )
                assert (
                    await session.scalar(text("SELECT count(*) FROM reconstructions"))
                    == 1
                )  # Only the fixture's existing reconstruction remains.
                async with asyncio.timeout(1):
                    async with IdempotencyService(session).operation(
                        owner_id=state.user_id,
                        idempotency_key=key,
                    ) as should_run:
                        assert should_run
                        await ReconstructionService(session).add_from_upload(
                            user_id=state.user_id,
                            building_id=state.building_id,
                            upload_id=state.upload_id,
                            settings=SplatGenerationWorkflowSettings(),
                        )

    asyncio.run(run())


def test_idempotency_keys_are_isolated_by_owner_and_survive_resource_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            other_owner = uuid4()
            async with AsyncSession(state.engine, expire_on_commit=False) as session:
                session.add(User(id=other_owner, keycloak_sub=str(other_owner)))
                await session.commit()

                async with IdempotencyService(session).operation(
                    owner_id=state.user_id,
                    idempotency_key="same-key",
                ) as should_run:
                    assert should_run
                    async with AsyncSession(
                        state.engine, expire_on_commit=False
                    ) as other:
                        async with asyncio.timeout(1):
                            async with IdempotencyService(other).operation(
                                owner_id=other_owner,
                                idempotency_key="same-key",
                            ) as should_run:
                                assert should_run
                            async with IdempotencyService(other).operation(
                                owner_id=state.user_id,
                                idempotency_key="different-key",
                            ) as should_run:
                                assert should_run

                # Resource deletion must not make an accepted action reusable.
                building = await session.get(Building, state.building_id)
                assert building is not None
                await session.delete(building)
                await session.commit()
                async with IdempotencyService(session).operation(
                    owner_id=state.user_id,
                    idempotency_key="same-key",
                ) as should_run:
                    assert not should_run

                # User deletion cascades only that owner's records.
                owner = await session.get(User, state.user_id)
                assert owner is not None
                await session.delete(owner)
                await session.commit()
                assert (
                    await session.scalar(
                        text("SELECT count(*) FROM idempotency_records")
                    )
                    == 1
                )

    asyncio.run(run())


@pytest.mark.parametrize("new_building", [False, True])
@pytest.mark.parametrize("pause_during", ["acceptance", "scheduling"])
def test_submission_http_race_returns_conflict_or_completed_without_waiting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    new_building: bool,
    pause_during: str,
) -> None:
    async def run() -> None:
        async with database(tmp_path, monkeypatch) as state:
            paused = asyncio.Event()
            release = asyncio.Event()
            original_add = ReconstructionService.add_from_upload
            schedule = AsyncMock(return_value=uuid4())

            async def add_with_pause(service, **kwargs):
                reconstruction = await original_add(service, **kwargs)
                if pause_during == "acceptance":
                    paused.set()
                    await release.wait()
                return reconstruction

            async def register(**kwargs):
                if pause_during == "scheduling":
                    paused.set()
                    await release.wait()
                return await schedule(**kwargs)

            monkeypatch.setattr(
                ReconstructionService, "add_from_upload", add_with_pause
            )
            monkeypatch.setattr(
                splat_generation, "schedule_splat_generation_from_upload", register
            )

            async def session_override() -> AsyncIterator[AsyncSession]:
                async with AsyncSession(
                    state.engine, expire_on_commit=False
                ) as session:
                    yield session

            app = FastAPI()
            app.include_router(building_views.router, prefix="/buildings")
            app.include_router(
                reconstruction_views.router,
                prefix="/buildings/{building_id}/reconstructions",
            )
            app.dependency_overrides[get_session] = session_override
            app.dependency_overrides[require_user] = lambda: User(id=state.user_id)
            url = (
                "/buildings/from-reconstruction/from-upload"
                if new_building
                else f"/buildings/{state.building_id}/reconstructions/from-upload"
            )
            headers = {"Idempotency-Key": str(uuid4())}
            payload = {"upload_id": str(state.upload_id)}
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                first = asyncio.create_task(
                    client.post(url, headers=headers, json=payload)
                )
                try:
                    async with asyncio.timeout(5):
                        await paused.wait()
                    async with asyncio.timeout(1):
                        second = await client.post(url, headers=headers, json=payload)
                    if pause_during == "acceptance":
                        assert second.status_code == 409
                        assert second.json() == {
                            "detail": {"code": "idempotency_in_progress"}
                        }
                        assert second.headers["Retry-After"] == "1"
                    else:
                        assert second.status_code == 204
                        assert second.content == b""
                finally:
                    release.set()
                    response = await asyncio.wait_for(first, 5)
                assert response.status_code == 202
                row = (
                    response.json()["reconstruction"]
                    if new_building
                    else response.json()
                )
                assert row["status"] == "scheduled"
                assert schedule.await_count == 1
                replay = await client.post(url, headers=headers, json=payload)
                assert replay.status_code == 204
                assert replay.content == b""

    asyncio.run(run())
