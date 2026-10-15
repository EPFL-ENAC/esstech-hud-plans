import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from api.config import config
from api.db import get_session
from api.lib.upload_storage import upload_file_path
from api.models.building import Building
from api.models.reconstruction import Reconstruction
from api.models.uploads import (
    UploadStatus,
    UserUploadCreate,
    UserUploadRead,
    UserUploads,
    UserUploadUpdate,
)
from api.models.user import User, utc_now
from api.services.auth import require_user
from api.services.uploads import (
    SortOrder,
    UploadConflictError,
    UploadNotFoundError,
    UserUploadsService,
)
from api.views import uploads as upload_views

USER_ID = UUID(int=1)
OTHER_USER_ID = UUID(int=2)


@pytest.fixture(autouse=True)
def upload_directories(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(config, "TUSD_UPLOAD_DIR", str(tmp_path / "tus"))
    Path(config.TUSD_UPLOAD_DIR).mkdir()


@pytest.fixture
def database() -> Iterator[AsyncEngine]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(connection: object, record: object) -> None:
        connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    User(id=USER_ID, keycloak_sub="subject-1"),
                    User(id=OTHER_USER_ID, keycloak_sub="subject-2"),
                ]
            )
            await session.commit()

    asyncio.run(prepare_database())
    try:
        yield engine
    finally:
        asyncio.run(engine.dispose())


@asynccontextmanager
async def uploads_service(
    engine: AsyncEngine,
) -> AsyncIterator[tuple[UserUploadsService, AsyncSession]]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield UserUploadsService(session), session


@pytest.fixture
def api_client(database: AsyncEngine) -> Iterator[TestClient]:
    async def session_override() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(database, expire_on_commit=False) as session:
            yield session

    app = FastAPI()
    app.state.upload_database = database
    app.include_router(upload_views.router, prefix="/uploads")
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[require_user] = lambda: User(
        id=USER_ID,
        keycloak_sub="subject-1",
    )
    with TestClient(app) as client:
        yield client


def _create_upload(
    api_client: TestClient,
    *,
    uploaded: bool = False,
    payload: UserUploadCreate | None = None,
) -> dict[str, Any]:
    assert isinstance(api_client.app, FastAPI)
    engine = api_client.app.state.upload_database

    async def create() -> dict[str, Any]:
        async with uploads_service(engine) as (uploads, session):
            upload = await uploads.create(
                user_id=USER_ID,
                payload=payload or UserUploadCreate(),
                filename="video.mp4",
                size_bytes=11,
                file_path="TODO",
            )
            if uploaded:
                upload.status = UploadStatus.UPLOADED
                upload.uploaded_at = utc_now()
                session.add(upload)
                await session.commit()
                await session.refresh(upload)
            return UserUploadRead.model_validate(upload).model_dump(mode="json")

    return asyncio.run(create())


def test_upload_defaults_and_column_types() -> None:
    upload = UserUploads(
        user_id=USER_ID,
        filename="video.mp4",
        size_bytes=0,
        file_path="TODO",
    )
    assert isinstance(upload.id, UUID)
    assert upload.name == "TODO"
    assert upload.description == ""
    assert upload.status == UploadStatus.PENDING
    assert upload.created_at.tzinfo == UTC
    assert upload.uploaded_at is None
    table = SQLModel.metadata.tables["user_uploads"]
    assert isinstance(table.c.size_bytes.type, BigInteger)
    created_at_type = table.c.created_at.type
    uploaded_at_type = table.c.uploaded_at.type
    assert isinstance(created_at_type, DateTime)
    assert isinstance(uploaded_at_type, DateTime)
    assert created_at_type.timezone is True
    assert uploaded_at_type.timezone is True
    assert table.c.uploaded_at.nullable is True
    assert not issubclass(UserUploadCreate, SQLModel)
    assert not issubclass(UserUploadUpdate, SQLModel)
    assert not issubclass(UserUploadRead, SQLModel)


def test_upload_service_crud_preserves_file(
    database: AsyncEngine,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "video.mp4"
    file_path.write_bytes(b"existing file")

    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            upload = await uploads.create(
                user_id=USER_ID,
                payload=UserUploadCreate(),
                filename=file_path.name,
                size_bytes=2**32,
                file_path=str(file_path),
            )
            upload_id = upload.id
            assert await uploads.get(upload_id, user_id=OTHER_USER_ID) is None
            assert await uploads.get(uuid4(), user_id=USER_ID) is None
            assert await uploads.list(user_id=OTHER_USER_ID) == []

            session.expunge_all()
            persisted = await uploads.get(upload_id, user_id=USER_ID)
            assert persisted is not None
            assert persisted.file_path == str(file_path)
            original = UserUploadRead.model_validate(persisted).model_dump()
            assert original["size_bytes"] == 2**32
            assert original["status"] == UploadStatus.PENDING
            assert original["uploaded_at"] is None

            updated = await uploads.update(
                persisted,
                UserUploadUpdate(name="Video", description="A building"),
            )
            assert UserUploadRead.model_validate(updated).model_dump() == {
                **original,
                "name": "Video",
                "description": "A building",
            }
            assert await uploads.update(updated, UserUploadUpdate()) is updated
            updated.status = UploadStatus.UPLOADED
            session.add(updated)
            await session.commit()
            await uploads.delete(updated)
            assert await uploads.get(upload_id, user_id=USER_ID) is None

    asyncio.run(run())
    assert file_path.read_bytes() == b"existing file"


@pytest.mark.parametrize("sort_order", ["asc", "desc"])
def test_upload_list_orders_and_scopes_before_pagination(
    database: AsyncEngine,
    sort_order: SortOrder,
) -> None:
    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            timestamp = datetime(2026, 10, 13, tzinfo=UTC)
            owned = [
                UserUploads(
                    id=UUID(int=100 - index),
                    user_id=USER_ID,
                    filename="video.mp4",
                    size_bytes=0,
                    file_path="TODO",
                    created_at=timestamp + timedelta(days=index // 2),
                )
                for index in range(6)
            ]
            session.add_all(owned)
            session.add(
                UserUploads(
                    user_id=OTHER_USER_ID,
                    filename="other.mp4",
                    size_bytes=0,
                    file_path="TODO",
                    created_at=timestamp,
                )
            )
            await session.commit()
            expected = sorted(
                owned,
                key=lambda upload: (upload.created_at, upload.id),
                reverse=sort_order == "desc",
            )
            for offset in range(0, 8, 2):
                page = await uploads.list(
                    user_id=USER_ID,
                    offset=offset,
                    limit=2,
                    sort_order=sort_order,
                )
                assert [upload.id for upload in page] == [
                    upload.id for upload in expected[offset : offset + 2]
                ]

    asyncio.run(run())


@pytest.mark.parametrize(
    "pagination",
    [
        {"offset": -1},
        {"limit": 0},
        {"limit": 101},
        {"sort_order": "invalid"},
    ],
)
def test_upload_service_validates_pagination(
    database: AsyncEngine,
    pagination: dict[str, object],
) -> None:
    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            with pytest.raises(ValueError):
                await uploads.list(user_id=USER_ID, **pagination)  # type: ignore[arg-type]

    asyncio.run(run())


def test_failed_creation_rolls_back(database: AsyncEngine) -> None:
    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            with pytest.raises(IntegrityError):
                await uploads.create(
                    user_id=uuid4(),
                    payload=UserUploadCreate(),
                    filename="missing-owner.mp4",
                    size_bytes=0,
                    file_path="TODO",
                )
            assert await uploads.list(user_id=USER_ID) == []
            created = await uploads.create(
                user_id=USER_ID,
                payload=UserUploadCreate(),
                filename="video.mp4",
                size_bytes=0,
                file_path="TODO",
            )
            assert created.user_id == USER_ID

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_failed_mutation_rolls_back(
    database: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            created = await uploads.create(
                user_id=USER_ID,
                payload=UserUploadCreate(),
                filename="video.mp4",
                size_bytes=0,
                file_path="TODO",
            )
            upload_id = created.id
            if operation == "delete":
                created.status = UploadStatus.UPLOADED
                session.add(created)
                await session.commit()
            with monkeypatch.context() as patches:
                patches.setattr(
                    session,
                    "commit",
                    AsyncMock(side_effect=OperationalError("commit", {}, Exception())),
                )
                with pytest.raises(OperationalError):
                    if operation == "update":
                        await uploads.update(created, UserUploadUpdate(name="Changed"))
                    else:
                        await uploads.delete(created)
            persisted = await uploads.get(upload_id, user_id=USER_ID)
            assert persisted is not None
            assert persisted.name == "TODO"

    asyncio.run(run())


def test_upload_routes_cover_crud(api_client: TestClient) -> None:
    created = _create_upload(api_client, uploaded=True)
    upload_id = created["id"]
    assert UUID(upload_id)
    assert datetime.fromisoformat(created["created_at"])
    assert created == {
        "id": upload_id,
        "user_id": str(USER_ID),
        "name": "TODO",
        "description": "",
        "filename": "video.mp4",
        "size_bytes": 11,
        "status": "uploaded",
        "created_at": created["created_at"],
        "uploaded_at": created["uploaded_at"],
    }
    assert api_client.get("/uploads").json() == [created]
    assert api_client.get(f"/uploads/{upload_id}").json() == created
    updated = api_client.patch(
        f"/uploads/{upload_id}",
        json={"name": "My video"},
    )
    assert updated.status_code == 200
    assert updated.json() == {**created, "name": "My video"}
    updated = api_client.patch(
        f"/uploads/{upload_id}",
        json={"description": "My description"},
    )
    assert updated.json() == {
        **created,
        "name": "My video",
        "description": "My description",
    }
    assert api_client.patch(f"/uploads/{upload_id}", json={}).json() == updated.json()
    assert api_client.get(f"/uploads/{upload_id}").json() == updated.json()
    deleted = api_client.delete(f"/uploads/{upload_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert api_client.get(f"/uploads/{upload_id}").status_code == 404
    assert api_client.get("/uploads").json() == []


def test_upload_creation_accepts_user_metadata(api_client: TestClient) -> None:
    created = _create_upload(
        api_client,
        payload=UserUploadCreate(name="Video", description="A building"),
    )
    assert created["name"] == "Video"
    assert created["description"] == "A building"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": None},
        {"description": None},
        {"id": str(USER_ID)},
        {"user_id": str(OTHER_USER_ID)},
        {"filename": "video.mp4"},
        {"size_bytes": 100},
        {"file_path": "/some/path"},
        {"status": "uploaded"},
        {"created_at": "2026-10-13T00:00:00Z"},
        {"uploaded_at": "2026-10-13T00:00:00Z"},
    ],
)
def test_upload_routes_reject_nulls_and_noneditable_fields(
    api_client: TestClient,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        UserUploadCreate.model_validate(payload)
    created = _create_upload(api_client)
    path = f"/uploads/{created['id']}"
    assert api_client.patch(path, json=payload).status_code == 422
    assert api_client.get(f"/uploads/{created['id']}").json() == created


@pytest.mark.parametrize(
    "query",
    ["offset=-1", "limit=0", "limit=101", "sort_order=invalid"],
)
def test_upload_routes_validate_pagination(api_client: TestClient, query: str) -> None:
    assert api_client.get(f"/uploads?{query}").status_code == 422


def test_upload_routes_hide_other_users_rows(api_client: TestClient) -> None:
    created = _create_upload(api_client)
    assert isinstance(api_client.app, FastAPI)
    api_client.app.dependency_overrides[require_user] = lambda: User(
        id=OTHER_USER_ID,
        keycloak_sub="subject-2",
    )
    assert api_client.get("/uploads").json() == []
    for upload_id in [created["id"], str(uuid4())]:
        for method in ["get", "patch", "delete"]:
            response = api_client.request(method, f"/uploads/{upload_id}", json={})
            assert response.status_code == 404
            assert response.json() == {"detail": "Upload not found"}
    api_client.app.dependency_overrides[require_user] = lambda: User(
        id=USER_ID,
        keycloak_sub="subject-1",
    )
    assert api_client.get(f"/uploads/{created['id']}").json() == created


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/uploads"),
        ("get", f"/uploads/{USER_ID}"),
        ("patch", f"/uploads/{USER_ID}"),
        ("delete", f"/uploads/{USER_ID}"),
    ],
)
def test_upload_routes_require_authentication(
    api_client: TestClient,
    method: str,
    path: str,
) -> None:
    assert isinstance(api_client.app, FastAPI)
    del api_client.app.dependency_overrides[require_user]
    assert api_client.request(method, path, json={}).status_code == 401


@pytest.mark.parametrize(
    "failure",
    [OSError("unavailable"), OperationalError("", {}, Exception())],
)
@pytest.mark.parametrize("operation", ["list", "get", "update", "delete"])
def test_upload_routes_map_database_failures(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    failure: Exception,
) -> None:
    upload_id = _create_upload(api_client, uploaded=True)["id"]
    monkeypatch.setattr(
        UserUploadsService,
        operation,
        AsyncMock(side_effect=failure),
    )
    method, path = {
        "list": ("get", "/uploads"),
        "get": ("get", f"/uploads/{upload_id}"),
        "update": ("patch", f"/uploads/{upload_id}"),
        "delete": ("delete", f"/uploads/{upload_id}"),
    }[operation]
    response = api_client.request(method, path, json={"name": "Changed"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Upload database is unavailable"}


def test_upload_router_is_registered_in_application() -> None:
    from api.main import app

    schema = app.openapi()
    paths = schema["paths"]
    assert "get" in paths["/uploads"]
    assert "post" not in paths["/uploads"]
    assert {"get", "patch", "delete"} <= paths["/uploads/{upload_id}"].keys()
    properties = schema["components"]["schemas"]["UserUploadRead"]["properties"]
    assert "file_path" not in properties


def test_upload_migration_preserves_existing_tables_and_cascades() -> None:
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "migrations"),
    )
    scripts = ScriptDirectory.from_config(config)
    migration = scripts.get_revision("32120c241602")
    assert migration is not None
    assert migration.down_revision == "c82a6f419d03"
    assert isinstance(migration.down_revision, str)
    user_table = SQLModel.metadata.tables["users"]
    building_table = SQLModel.metadata.tables[Building.__tablename__]
    reconstruction_table = SQLModel.metadata.tables[Reconstruction.__tablename__]
    upload_table = SQLModel.metadata.tables["user_uploads"]
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            unmanaged = Table(
                "prefect_flow_run",
                MetaData(),
                Column("id", Integer, primary_key=True),
            )
            unmanaged.create(connection)
            connection.execute(unmanaged.insert().values(id=1))
            with Operations.context(MigrationContext.configure(connection)):
                for revision in reversed(
                    list(
                        scripts.walk_revisions(
                            base="base",
                            head=migration.down_revision,
                        )
                    )
                ):
                    revision.module.upgrade()
                connection.execute(
                    user_table.insert().values(
                        id=USER_ID,
                        keycloak_sub="existing",
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
                connection.execute(
                    building_table.insert().values(
                        id=USER_ID,
                        user_id=USER_ID,
                        name="Existing building",
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
                connection.execute(
                    reconstruction_table.insert().values(
                        id=USER_ID,
                        building_id=USER_ID,
                        settings={},
                        status="preparing",
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                )
                existing_tables = [
                    "users",
                    "buildings",
                    "reconstructions",
                    "prefect_flow_run",
                ]
                before = {
                    table: connection.execute(text(f"SELECT * FROM {table}")).all()
                    for table in existing_tables
                }
                migration.module.upgrade()

                inspector = inspect(connection)
                columns = {
                    column["name"]: column
                    for column in inspector.get_columns("user_uploads")
                }
                assert isinstance(columns["size_bytes"]["type"], BigInteger)
                assert columns["uploaded_at"]["nullable"] is True
                assert columns["created_at"]["nullable"] is False
                foreign_key = inspector.get_foreign_keys("user_uploads")[0]
                assert foreign_key["referred_table"] == "users"
                assert foreign_key["options"] == {"ondelete": "CASCADE"}
                assert inspector.get_indexes("user_uploads")[0]["column_names"] == [
                    "user_id"
                ]

                connection.execute(
                    upload_table.insert().values(
                        user_id=USER_ID,
                        filename="video.mp4",
                        size_bytes=2**32,
                        file_path="TODO",
                        status="pending",
                        created_at=datetime.now(UTC),
                    )
                )
                assert (
                    connection.execute(
                        text("SELECT size_bytes FROM user_uploads")
                    ).scalar()
                    == 2**32
                )
                migration.module.downgrade()
                assert "user_uploads" not in inspect(connection).get_table_names()
                assert before == {
                    table: connection.execute(text(f"SELECT * FROM {table}")).all()
                    for table in existing_tables
                }

                migration.module.upgrade()
                connection.execute(
                    upload_table.insert().values(
                        user_id=USER_ID,
                        filename="video.mp4",
                        size_bytes=0,
                        file_path="TODO",
                        status="pending",
                        created_at=datetime.now(UTC),
                    )
                )
                connection.execute(
                    user_table.delete().where(user_table.c.id == USER_ID)
                )
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM user_uploads")
                    ).scalar()
                    == 0
                )
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM prefect_flow_run")
                    ).scalar()
                    == 1
                )
    finally:
        engine.dispose()


def test_upload_post_is_removed(api_client: TestClient) -> None:
    assert api_client.post("/uploads", json={}).status_code == 405
    assert api_client.get("/uploads").json() == []


def test_pending_upload_cannot_be_deleted(api_client: TestClient) -> None:
    created = _create_upload(api_client)
    response = api_client.delete(f"/uploads/{created['id']}")
    assert response.status_code == 409
    assert response.json() == {"detail": "Upload has not finished uploading"}
    assert api_client.get(f"/uploads/{created['id']}").json() == created


def test_upload_registration_and_completion_are_idempotent(
    database: AsyncEngine,
) -> None:
    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            upload_id = uuid4()
            values: dict[str, Any] = {
                "upload_id": upload_id,
                "user_id": USER_ID,
                "payload": UserUploadCreate(),
                "filename": "video.mp4",
                "size_bytes": 11,
                "file_path": "TODO",
            }
            staging = Path(config.TUSD_UPLOAD_DIR) / upload_id.hex
            staging.write_bytes(b"video bytes")
            staging.with_name(staging.name + ".info").write_text("{}")
            values["file_path"] = str(staging)
            first = await uploads.create(**values)
            await uploads.update(first, UserUploadUpdate(name="Renamed"))
            completed = await uploads.complete(upload_id)
            destination = upload_file_path(upload_id, "video.mp4")
            assert completed.file_path == str(destination)
            assert destination.read_bytes() == b"video bytes"
            assert not staging.exists()
            assert not staging.with_name(staging.name + ".info").exists()
            timestamp = completed.uploaded_at
            assert timestamp is not None
            repeated = await uploads.create(**values)
            assert repeated.id == upload_id
            assert repeated.name == "Renamed"
            assert repeated.status == UploadStatus.UPLOADED
            assert repeated.uploaded_at == timestamp
            session.expunge_all()
            repeated = await uploads.complete(upload_id)
            assert repeated.uploaded_at == timestamp
            assert len(await uploads.list(user_id=USER_ID)) == 1

    asyncio.run(run())


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": OTHER_USER_ID},
        {"filename": "different.mp4"},
        {"size_bytes": 12},
    ],
)
def test_upload_registration_rejects_conflicting_ids(
    database: AsyncEngine,
    changes: dict[str, Any],
) -> None:
    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            values: dict[str, Any] = {
                "upload_id": uuid4(),
                "user_id": USER_ID,
                "payload": UserUploadCreate(),
                "filename": "video.mp4",
                "size_bytes": 11,
                "file_path": "TODO",
            }
            first = await uploads.create(**values)
            with pytest.raises(UploadConflictError):
                await uploads.create(**{**values, **changes})
            assert first.status == UploadStatus.PENDING
            assert first.filename == "video.mp4"
            assert len(await uploads.list(user_id=USER_ID)) == 1

    asyncio.run(run())


def test_upload_registration_recovers_from_duplicate_insert(
    database: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            values: dict[str, Any] = {
                "upload_id": uuid4(),
                "user_id": USER_ID,
                "payload": UserUploadCreate(),
                "filename": "video.mp4",
                "size_bytes": 11,
                "file_path": "TODO",
            }
            await uploads.create(**values)
            session.expunge_all()
            original_get = session.get
            calls = 0

            async def miss_initial_lookup(*args: Any, **kwargs: Any) -> Any:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return None
                return await original_get(*args, **kwargs)

            monkeypatch.setattr(session, "get", miss_initial_lookup)
            repeated = await uploads.create(**values)
            assert repeated.id == values["upload_id"]
            assert calls == 2
            assert len(await uploads.list(user_id=USER_ID)) == 1

    asyncio.run(run())


def test_upload_completion_rejects_missing_or_failed_rows(
    database: AsyncEngine,
) -> None:
    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            with pytest.raises(UploadNotFoundError):
                await uploads.complete(uuid4())
            failed = UserUploads(
                user_id=USER_ID,
                filename="video.mp4",
                size_bytes=11,
                file_path="TODO",
                status=UploadStatus.FAILED,
            )
            session.add(failed)
            await session.commit()
            upload_id = failed.id
            with pytest.raises(UploadConflictError):
                await uploads.complete(upload_id)
            persisted = await uploads.get(upload_id, user_id=USER_ID)
            assert persisted is not None
            assert persisted.status == UploadStatus.FAILED
            assert persisted.uploaded_at is None

    asyncio.run(run())


def test_failed_completion_rolls_back_and_reuses_copied_file(
    database: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_id = uuid4()
    source = Path(config.TUSD_UPLOAD_DIR) / upload_id.hex
    source.write_bytes(b"video bytes")
    info = source.with_name(source.name + ".info")
    info.write_text("{}")
    destination = upload_file_path(upload_id, "video.mp4")

    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            await uploads.create(
                upload_id=upload_id,
                user_id=USER_ID,
                payload=UserUploadCreate(),
                filename="video.mp4",
                size_bytes=11,
                file_path=str(source),
            )
            with monkeypatch.context() as patches:
                patches.setattr(
                    session,
                    "commit",
                    AsyncMock(side_effect=OperationalError("commit", {}, Exception())),
                )
                with pytest.raises(OperationalError):
                    await uploads.complete(upload_id)
            persisted = await uploads.get(upload_id, user_id=USER_ID)
            assert persisted is not None
            assert persisted.status == UploadStatus.PENDING
            assert persisted.uploaded_at is None
            assert persisted.file_path == str(source)
            assert source.read_bytes() == b"video bytes"
            assert info.exists()
            assert destination.read_bytes() == b"video bytes"

            def unexpected_copy(*args: object) -> None:
                raise AssertionError("A complete destination must be reused")

            with monkeypatch.context() as patches:
                patches.setattr(
                    "api.lib.upload_storage.shutil.copyfile", unexpected_copy
                )
                completed = await uploads.complete(upload_id)
            assert completed.file_path == str(destination)
            assert completed.status == UploadStatus.UPLOADED
            assert completed.uploaded_at is not None
            assert not source.exists()
            assert not info.exists()

    asyncio.run(run())


@pytest.mark.parametrize("contents", [None, b"", b"partial"])
def test_completion_does_not_publish_missing_or_incomplete_file(
    database: AsyncEngine,
    contents: bytes | None,
) -> None:
    upload_id = uuid4()
    source = Path(config.TUSD_UPLOAD_DIR) / upload_id.hex
    if contents is not None:
        source.write_bytes(contents)

    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            await uploads.create(
                upload_id=upload_id,
                user_id=USER_ID,
                payload=UserUploadCreate(),
                filename="video.mp4",
                size_bytes=11,
                file_path=str(source),
            )
            with pytest.raises(OSError):
                await uploads.complete(upload_id)
            persisted = await uploads.get(upload_id, user_id=USER_ID)
            assert persisted is not None
            assert persisted.status == UploadStatus.PENDING
            assert persisted.uploaded_at is None
            assert persisted.file_path == str(source)
            assert not upload_file_path(upload_id, "video.mp4").exists()

    asyncio.run(run())


def test_completion_retries_cleanup_without_losing_stored_file(
    database: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_id = uuid4()
    source = Path(config.TUSD_UPLOAD_DIR) / upload_id.hex
    source.write_bytes(b"video bytes")

    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            await uploads.create(
                upload_id=upload_id,
                user_id=USER_ID,
                payload=UserUploadCreate(),
                filename="video.mp4",
                size_bytes=11,
                file_path=str(source),
            )

            def fail_cleanup(upload_id: UUID) -> None:
                raise OSError("Busy")

            with monkeypatch.context() as patches:
                patches.setattr("api.services.uploads.remove_tus_files", fail_cleanup)
                stored = await uploads.complete(upload_id)
            timestamp = stored.uploaded_at
            assert stored.status == UploadStatus.UPLOADED
            assert Path(stored.file_path).read_bytes() == b"video bytes"
            assert source.exists()
            retried = await uploads.get_completed(upload_id, user_id=USER_ID)
            assert retried.uploaded_at == timestamp
            assert not source.exists()
            assert Path(retried.file_path).read_bytes() == b"video bytes"

    asyncio.run(run())


def test_get_completed_checks_ownership_before_moving_file(
    database: AsyncEngine,
) -> None:
    upload_id = uuid4()
    source = Path(config.TUSD_UPLOAD_DIR) / upload_id.hex
    source.write_bytes(b"video bytes")

    async def run() -> None:
        async with uploads_service(database) as (uploads, session):
            upload = await uploads.create(
                upload_id=upload_id,
                user_id=USER_ID,
                payload=UserUploadCreate(),
                filename="video.mp4",
                size_bytes=11,
                file_path=str(source),
            )
            with pytest.raises(UploadConflictError):
                await uploads.get_completed(upload_id, user_id=USER_ID)
            upload.status = UploadStatus.UPLOADED
            upload.uploaded_at = datetime(2026, 10, 14, tzinfo=UTC)
            session.add(upload)
            await session.commit()
            with pytest.raises(UploadNotFoundError):
                await uploads.get_completed(upload_id, user_id=OTHER_USER_ID)
            assert source.read_bytes() == b"video bytes"
            stored = await uploads.get_completed(upload_id, user_id=USER_ID)
            assert stored.uploaded_at is not None
            assert stored.uploaded_at.date() == datetime(2026, 10, 14).date()
            assert not source.exists()
            assert Path(stored.file_path).read_bytes() == b"video bytes"

    asyncio.run(run())
