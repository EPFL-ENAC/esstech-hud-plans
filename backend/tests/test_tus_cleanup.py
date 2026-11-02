import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from api.config import config
from api.lib.tus import tus_file_path
from api.lib.upload_storage import is_tus_upload_expired, upload_file_path
from api.lib.workflows import tus_cleanup
from api.models.building import Building
from api.models.reconstruction import Reconstruction, ReconstructionStatus
from api.models.uploads import UploadStatus, UserUploads
from api.models.user import User
from api.services.uploads import UserUploadsService

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)
USER_ID = UUID(int=1)
BUILDING_ID = UUID(int=2)


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[AsyncEngine]:
    staging = tmp_path / "tus"
    staging.mkdir()
    monkeypatch.setattr(config, "TUSD_UPLOAD_DIR", str(staging))
    monkeypatch.setattr(config, "TUSD_UPLOAD_RETENTION_DAYS", 7)
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(tus_cleanup, "utc_now", lambda: NOW)
    monkeypatch.setattr(tus_cleanup, "get_run_logger", Mock)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    monkeypatch.setattr(tus_cleanup, "get_engine", lambda: engine)

    async def prepare() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine) as session:
            session.add(User(id=USER_ID, keycloak_sub="cleanup-user"))
            session.add(Building(id=BUILDING_ID, user_id=USER_ID, name="Cleanup"))
            await session.commit()

    asyncio.run(prepare())
    try:
        yield engine
    finally:
        asyncio.run(engine.dispose())


def stage_file(path: Path, age_days: float) -> None:
    path.write_bytes(b"video bytes")
    timestamp = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (timestamp, timestamp))


def pending_upload(*, age_days: int = 8) -> UserUploads:
    upload_id = uuid4()
    return UserUploads(
        id=upload_id,
        user_id=USER_ID,
        filename="scan.mp4",
        size_bytes=11,
        uploaded_bytes=5,
        file_path=tus_file_path(upload_id),
        created_at=NOW - timedelta(days=age_days),
    )


def reconstruction(upload: UserUploads, status: ReconstructionStatus) -> Reconstruction:
    return Reconstruction(
        building_id=BUILDING_ID,
        upload_id=upload.id,
        status=status,
        settings={},
        updated_at=NOW - timedelta(days=1),
    )


@pytest.mark.parametrize(
    ("info_age", "binary_age", "created_age", "expected"),
    [
        (8, 8, None, True),
        (7, 8, None, False),
        (8, 1, None, False),
        (8, 0.1, None, False),
        (8, None, None, True),
        (1, None, None, False),
        (None, 2, None, True),
        (None, 1, None, False),
        (None, None, 8, True),
        (None, None, 7, False),
        (None, None, 1, False),
        (None, None, None, False),
    ],
)
def test_expiration_uses_staging_activity_and_missing_file_age(
    tmp_path: Path,
    info_age: float | None,
    binary_age: float | None,
    created_age: float | None,
    expected: bool,
) -> None:
    source = tmp_path / "upload"
    if info_age is not None:
        stage_file(tmp_path / "upload.info", info_age)
    if binary_age is not None:
        stage_file(source, binary_age)
    created_at = NOW - timedelta(days=created_age) if created_age is not None else None
    assert (
        is_tus_upload_expired(
            source,
            now=NOW,
            retention_days=7,
            created_at=created_at,
        )
        is expected
    )


@pytest.mark.parametrize("filename", ["upload", "upload.info"])
@pytest.mark.parametrize("error", [PermissionError("Denied"), OSError("I/O failure")])
def test_expiration_propagates_filesystem_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    filename: str,
    error: OSError,
) -> None:
    original_stat = Path.stat

    def fail_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        if path == tmp_path / filename:
            raise error
        return original_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", fail_stat)
    with pytest.raises(type(error), match=str(error)):
        is_tus_upload_expired(
            tmp_path / "upload",
            now=NOW,
            retention_days=7,
            created_at=NOW - timedelta(days=8),
        )


def test_cleanup_fails_only_abandoned_uploads_and_waiting_reconstructions(
    database: AsyncEngine,
) -> None:
    expired = pending_upload()
    active = pending_upload()
    completed = pending_upload()
    completed.status = UploadStatus.UPLOADED
    completed.uploaded_bytes = completed.size_bytes
    completed.uploaded_at = NOW - timedelta(days=8)
    permanent = upload_file_path(completed.id, completed.filename)
    permanent.parent.mkdir(parents=True)
    permanent.write_bytes(b"video bytes")
    completed.file_path = str(permanent)
    rows = [reconstruction(expired, status) for status in ReconstructionStatus]
    rows.append(reconstruction(active, ReconstructionStatus.WAITING_FOR_UPLOAD))
    rows.append(reconstruction(completed, ReconstructionStatus.COMPLETED))

    async def prepare() -> None:
        async with AsyncSession(database, expire_on_commit=False) as session:
            session.add_all([expired, active, completed, *rows])
            await session.commit()

    asyncio.run(prepare())
    for upload in (expired, active, completed):
        source = Path(tus_file_path(upload.id))
        stage_file(source, 8)
        stage_file(source.with_name(source.name + ".info"), 8)
    stage_file(Path(tus_file_path(active.id)), 0.1)
    orphan = Path(config.TUSD_UPLOAD_DIR) / "unregistered"
    stage_file(orphan, 2)
    nested = Path(config.TUSD_UPLOAD_DIR) / "nested"
    nested.mkdir()
    stage_file(nested / "untouched", 8)

    removed = asyncio.run(tus_cleanup.tus_cleanup_flow.fn())
    assert set(removed) == {expired.id.hex, completed.id.hex, "unregistered"}
    assert permanent.read_bytes() == b"video bytes"
    assert Path(tus_file_path(active.id)).exists()
    assert (nested / "untouched").exists()

    async def verify() -> None:
        async with AsyncSession(database, expire_on_commit=False) as session:
            stored = await session.get(UserUploads, expired.id)
            assert stored is not None
            assert stored.status == UploadStatus.FAILED
            assert stored.uploaded_bytes == 5
            assert stored.uploaded_at is None
            for upload in (active, completed):
                stored = await session.get(UserUploads, upload.id)
                assert stored is not None
                assert stored.status == upload.status
            for original in rows:
                row = await session.get(Reconstruction, original.id)
                assert row is not None
                if (
                    original.upload_id == expired.id
                    and original.status == ReconstructionStatus.WAITING_FOR_UPLOAD
                ):
                    assert row.status == ReconstructionStatus.FAILED
                    assert row.error_message == "Source upload expired"
                    assert row.updated_at.replace(tzinfo=UTC) == NOW
                else:
                    assert row.status == original.status
                    assert row.error_message is None
                    assert row.updated_at.replace(tzinfo=UTC) == NOW - timedelta(days=1)

    asyncio.run(verify())
    assert asyncio.run(tus_cleanup.tus_cleanup_flow.fn()) == []


def test_cleanup_repairs_old_pending_rows_without_staging_files(
    database: AsyncEngine,
) -> None:
    old = pending_upload()
    recent = pending_upload(age_days=1)
    waiting = reconstruction(old, ReconstructionStatus.WAITING_FOR_UPLOAD)

    async def prepare() -> None:
        async with AsyncSession(database, expire_on_commit=False) as session:
            session.add_all([old, recent, waiting])
            await session.commit()

    asyncio.run(prepare())
    assert asyncio.run(tus_cleanup.tus_cleanup_flow.fn()) == []

    async def verify() -> None:
        async with AsyncSession(database, expire_on_commit=False) as session:
            expired = await session.get(UserUploads, old.id)
            preserved = await session.get(UserUploads, recent.id)
            failed = await session.get(Reconstruction, waiting.id)
            assert expired is not None and expired.status == UploadStatus.FAILED
            assert preserved is not None and preserved.status == UploadStatus.PENDING
            assert failed is not None and failed.status == ReconstructionStatus.FAILED

    asyncio.run(verify())


@pytest.mark.parametrize("failure", ["database", "deletion"])
def test_cleanup_failures_preserve_transaction_order_and_allow_retry(
    database: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    upload = pending_upload()
    waiting = reconstruction(upload, ReconstructionStatus.WAITING_FOR_UPLOAD)
    source = Path(upload.file_path)
    stage_file(source, 8)
    stage_file(source.with_name(source.name + ".info"), 8)

    async def prepare() -> None:
        async with AsyncSession(database, expire_on_commit=False) as session:
            session.add_all([upload, waiting])
            await session.commit()

    asyncio.run(prepare())
    with monkeypatch.context() as patches:
        if failure == "database":
            patches.setattr(
                AsyncSession,
                "commit",
                AsyncMock(side_effect=OperationalError("commit", {}, Exception())),
            )
            error = OperationalError
        else:
            original_unlink = Path.unlink

            def fail_deletion(path: Path, *, missing_ok: bool = False) -> None:
                if path == source:
                    raise PermissionError("Busy")
                original_unlink(path, missing_ok=missing_ok)

            patches.setattr(Path, "unlink", fail_deletion)
            error = PermissionError
        with pytest.raises(error):
            asyncio.run(tus_cleanup.tus_cleanup_flow.fn())

    assert source.exists()

    async def verify() -> None:
        async with AsyncSession(database, expire_on_commit=False) as session:
            stored = await session.get(UserUploads, upload.id)
            row = await session.get(Reconstruction, waiting.id)
            assert stored is not None and row is not None
            if failure == "database":
                assert stored.status == UploadStatus.PENDING
                assert row.status == ReconstructionStatus.WAITING_FOR_UPLOAD
                assert row.error_message is None
            else:
                assert stored.status == UploadStatus.FAILED
                assert row.status == ReconstructionStatus.FAILED
                assert row.error_message == "Source upload expired"

    asyncio.run(verify())
    assert asyncio.run(tus_cleanup.tus_cleanup_flow.fn()) == [upload.id.hex]
    assert not source.exists()


def test_cleanup_skips_missing_staging_directory(
    database: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = pending_upload()

    async def prepare() -> None:
        async with AsyncSession(database, expire_on_commit=False) as session:
            session.add(upload)
            await session.commit()

    asyncio.run(prepare())
    Path(config.TUSD_UPLOAD_DIR).rmdir()
    get_engine = Mock(side_effect=AssertionError("Cleanup must skip the database"))
    monkeypatch.setattr(tus_cleanup, "get_engine", get_engine)
    assert asyncio.run(tus_cleanup.tus_cleanup_flow.fn()) == []
    get_engine.assert_not_called()

    async def verify() -> None:
        async with AsyncSession(database, expire_on_commit=False) as session:
            stored = await session.get(UserUploads, upload.id)
            assert stored is not None and stored.status == UploadStatus.PENDING

    asyncio.run(verify())


def test_expiration_rechecks_upload_status_after_candidate_scan(
    database: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = pending_upload()
    stage_file(Path(upload.file_path), 8)

    async def run() -> None:
        async with AsyncSession(database, expire_on_commit=False) as session:
            session.add(upload)
            await session.commit()
            uploads = UserUploadsService(session)
            original_get = uploads._get_for_update

            async def complete_before_lock(upload_id: UUID) -> UserUploads:
                await UserUploadsService(session).complete(upload_id)
                return await original_get(upload_id)

            monkeypatch.setattr(uploads, "_get_for_update", complete_before_lock)
            assert (
                await uploads.expire_abandoned_uploads(now=NOW, retention_days=7) == []
            )
            await session.refresh(upload)
            assert upload.status == UploadStatus.UPLOADED
            assert Path(upload.file_path).read_bytes() == b"video bytes"

    asyncio.run(run())
