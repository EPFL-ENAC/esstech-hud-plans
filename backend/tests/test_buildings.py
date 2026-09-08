import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from api.db import get_session
from api.models.building import (
    Building,
    BuildingCreate,
    BuildingListItemRead,
    BuildingLocationRead,
    BuildingRead,
    BuildingUpdate,
)
from api.models.reconstruction import (
    Reconstruction,
    ReconstructionStatus,
    ReconstructionSummary,
)
from api.models.user import User
from api.services.auth import require_user
from api.services.buildings import (
    BuildingService,
    ReconstructionStatusFilter,
    SortOrder,
)
from api.views import buildings as building_views
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")


@asynccontextmanager
async def building_service() -> AsyncIterator[tuple[BuildingService, AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    User(id=USER_ID, keycloak_sub="subject-1"),
                    User(id=OTHER_USER_ID, keycloak_sub="subject-2"),
                ]
            )
            await session.commit()
            yield BuildingService(session), session
    finally:
        await engine.dispose()


def test_only_building_row_inherits_from_sqlmodel() -> None:
    assert issubclass(BuildingCreate, BaseModel)
    assert issubclass(BuildingUpdate, BaseModel)
    assert issubclass(BuildingRead, BaseModel)
    assert not issubclass(BuildingCreate, SQLModel)
    assert not issubclass(BuildingUpdate, SQLModel)
    assert not issubclass(BuildingRead, SQLModel)
    assert issubclass(BuildingListItemRead, BuildingRead)
    assert not issubclass(BuildingListItemRead, SQLModel)
    assert Building.__tablename__ == "buildings"
    assert (
        Building.__mapper__.relationships["reconstructions"].mapper.class_
        is Reconstruction
    )
    assert User.__mapper__.relationships["buildings"].back_populates == "user"
    assert Building.__mapper__.relationships["user"].back_populates == "buildings"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "EPFL", "latitude": -90.01, "longitude": 6.57},
        {"name": "EPFL", "latitude": 90.01, "longitude": 6.57},
        {"name": "EPFL", "latitude": 46.52, "longitude": -180.01},
        {"name": "EPFL", "latitude": 46.52, "longitude": 180.01},
        {"name": "EPFL", "latitude": 46.52},
        {"name": "EPFL", "longitude": 6.57},
        {"name": "EPFL", "latitude": None, "longitude": 6.57},
    ],
)
def test_building_create_validates_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BuildingCreate.model_validate(payload)


def test_building_create_defaults_to_empty_optional_metadata() -> None:
    payload = BuildingCreate()
    assert payload.name == ""
    assert payload.address is None
    assert payload.latitude is None
    assert payload.longitude is None


def test_building_address_migration_preserves_existing_rows() -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    scripts = ScriptDirectory.from_config(config)
    migration = scripts.get_revision("c82a6f419d03")
    assert migration is not None
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                for revision in reversed(
                    list(
                        scripts.walk_revisions(
                            base="base", head=migration.down_revision
                        )
                    )
                ):
                    revision.module.upgrade()
                connection.execute(
                    text(
                        "INSERT INTO buildings "
                        "(id, user_id, name, latitude, longitude, created_at, updated_at) "
                        "VALUES (:id, :user_id, 'Existing building', NULL, NULL, :now, :now)"
                    ),
                    {
                        "id": USER_ID.hex,
                        "user_id": USER_ID.hex,
                        "now": datetime.now(UTC).isoformat(),
                    },
                )
                migration.module.upgrade()
                assert (
                    connection.execute(text("SELECT address FROM buildings")).scalar()
                    is None
                )
                connection.execute(text("UPDATE buildings SET address = 'New address'"))
                assert (
                    connection.execute(text("SELECT address FROM buildings")).scalar()
                    == "New address"
                )
                migration.module.downgrade()
                assert "address" not in {
                    column["name"]
                    for column in inspect(connection).get_columns("buildings")
                }
                assert (
                    connection.execute(text("SELECT name FROM buildings")).scalar()
                    == "Existing building"
                )
    finally:
        engine.dispose()


def test_building_update_rejects_null_name() -> None:
    with pytest.raises(ValidationError):
        BuildingUpdate.model_validate({"name": None})


@pytest.mark.parametrize(
    "payload",
    [
        {"latitude": 46.52},
        {"longitude": 6.57},
        {"latitude": None, "longitude": 6.57},
    ],
)
def test_building_update_requires_a_complete_coordinate_pair(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        BuildingUpdate.model_validate(payload)


def test_building_service_crud_and_ownership() -> None:
    async def run() -> None:
        async with building_service() as (buildings, session):
            first = await buildings.create(
                user_id=USER_ID,
                payload=BuildingCreate(
                    name="Main building",
                    latitude=46.5191,
                    longitude=6.5668,
                ),
            )
            duplicate_name = await buildings.create(
                user_id=USER_ID,
                payload=BuildingCreate(
                    name="Main building",
                    latitude=46.5200,
                    longitude=6.5700,
                ),
            )
            other_user_building = await buildings.create(
                user_id=OTHER_USER_ID,
                payload=BuildingCreate(
                    name="Main building",
                    latitude=47.0,
                    longitude=7.0,
                ),
            )

            assert await buildings.get(first.id, user_id=USER_ID) == first
            assert await buildings.get(first.id, user_id=OTHER_USER_ID) is None
            listed = await buildings.list(user_id=USER_ID)
            assert [item.id for item in listed] == [duplicate_name.id, first.id]
            assert all(item.latest_reconstruction is None for item in listed)
            assert [
                item.id for item in await buildings.list(user_id=OTHER_USER_ID)
            ] == [other_user_building.id]
            assert [
                item.id
                for item in await buildings.list(user_id=USER_ID, offset=1, limit=1)
            ] == [first.id]

            original_updated_at = first.updated_at
            unchanged = await buildings.update(first, BuildingUpdate())
            assert unchanged.updated_at == original_updated_at

            updated = await buildings.update(
                first,
                BuildingUpdate(name="Renamed", latitude=46.6, longitude=6.7),
            )
            assert updated.name == "Renamed"
            assert updated.latitude == 46.6
            assert updated.longitude == 6.7
            assert updated.updated_at > original_updated_at

            cleared = await buildings.update(
                updated,
                BuildingUpdate(latitude=None, longitude=None),
            )
            assert cleared.latitude is None
            assert cleared.longitude is None

            await buildings.delete(updated)
            assert await buildings.get(first.id, user_id=USER_ID) is None
            assert (await session.exec(select(Building))).all() == [
                duplicate_name,
                other_user_building,
            ]

    asyncio.run(run())


@pytest.mark.parametrize("sort_order", ["asc", "desc"])
def test_building_list_orders_before_pagination(sort_order: SortOrder) -> None:
    async def run() -> None:
        async with building_service() as (buildings, session):
            timestamp = datetime(2026, 9, 8, tzinfo=UTC)
            # IDs deliberately disagree with creation order. Equal dates use ID.
            oldest = Building(
                id=UUID(int=30),
                user_id=USER_ID,
                name="Oldest",
                created_at=timestamp - timedelta(days=1),
            )
            tied_first = Building(
                id=UUID(int=10),
                user_id=USER_ID,
                name="First tie",
                created_at=timestamp,
            )
            tied_second = Building(
                id=UUID(int=20),
                user_id=USER_ID,
                name="Second tie",
                created_at=timestamp,
            )
            other_user = Building(
                id=UUID(int=40),
                user_id=OTHER_USER_ID,
                name="Other owner",
                created_at=timestamp + timedelta(days=1),
            )
            session.add_all([tied_second, other_user, oldest, tied_first])
            # Multiple attempts must not multiply building rows or consume page slots.
            session.add_all(
                [
                    Reconstruction(building_id=building.id, settings={})
                    for building in [tied_first, tied_second, other_user]
                    for _ in range(3)
                ]
            )
            await session.commit()

            expected = [oldest, tied_first, tied_second]
            if sort_order == "desc":
                expected.reverse()
            listed = await buildings.list(
                user_id=USER_ID,
                sort_order=sort_order,
            )
            assert [item.id for item in listed] == [
                building.id for building in expected
            ]
            pages = [
                await buildings.list(
                    user_id=USER_ID,
                    sort_order=sort_order,
                    offset=index,
                    limit=1,
                )
                for index in range(3)
            ]
            assert [[item.id for item in page] for page in pages] == [
                [building.id] for building in expected
            ]
            assert (
                await buildings.list(
                    user_id=USER_ID,
                    sort_order=sort_order,
                    offset=3,
                    limit=1,
                )
                == []
            )

    asyncio.run(run())


def test_building_list_validates_pagination() -> None:
    async def run() -> None:
        async with building_service() as (buildings, _):
            for offset, limit in ((-1, 100), (0, 0), (0, 101)):
                with pytest.raises(ValueError):
                    await buildings.list(
                        user_id=USER_ID,
                        offset=offset,
                        limit=limit,
                    )

    asyncio.run(run())


@pytest.mark.parametrize("sort_order", ["asc", "desc"])
@pytest.mark.parametrize("reconstruction_status", [None, "processing", "idle"])
@pytest.mark.parametrize("search", [None, "hall"])
def test_building_list_filters_before_pagination(
    sort_order: SortOrder,
    reconstruction_status: ReconstructionStatusFilter | None,
    search: str | None,
) -> None:
    async def run() -> None:
        async with building_service() as (buildings, session):
            timestamp = datetime(2026, 9, 8, tzinfo=UTC)
            owned = [
                Building(
                    id=UUID(int=100 - index),
                    user_id=USER_ID,
                    name=f"{'Hall' if index % 4 < 2 else 'House'} {index}",
                    # Exercise timestamp sorting and UUID tie-breaking.
                    created_at=timestamp + timedelta(days=index // 4),
                )
                for index in range(8)
            ]
            others = [
                Building(user_id=OTHER_USER_ID, name="Other owner's Hall")
                for _ in range(2)
            ]
            session.add_all([*owned, *others])
            processing = owned[1::2]
            for building in [*processing, others[0]]:
                session.add_all(
                    [
                        Reconstruction(
                            building_id=building.id,
                            settings={},
                            status=ReconstructionStatus.RUNNING,
                        )
                        for _ in range(3)
                    ]
                )
            await session.commit()

            matching_names = owned if search is None else [*owned[:2], *owned[4:6]]
            expected = sorted(
                (
                    building
                    for building in matching_names
                    if reconstruction_status is None
                    or (building in processing)
                    == (reconstruction_status == "processing")
                ),
                key=lambda building: (building.created_at, building.id),
                reverse=sort_order == "desc",
            )
            actual = await buildings.list(
                user_id=USER_ID,
                sort_order=sort_order,
                reconstruction_status=reconstruction_status,
                search=search,
            )
            assert [item.id for item in actual] == [item.id for item in expected]
            for offset in range(0, len(expected) + 1, 2):
                page = await buildings.list(
                    user_id=USER_ID,
                    sort_order=sort_order,
                    reconstruction_status=reconstruction_status,
                    search=search,
                    offset=offset,
                    limit=2,
                )
                assert [item.id for item in page] == [
                    item.id for item in expected[offset : offset + 2]
                ]

    asyncio.run(run())


def test_building_locations_return_all_owned_coordinates_in_one_query() -> None:
    async def run() -> None:
        async with building_service() as (buildings, session):
            located = [
                Building(
                    id=UUID(int=index + 100),
                    user_id=USER_ID,
                    name=f"Building {index}",
                    latitude=0,
                    longitude=index,
                )
                for index in range(105)
            ]
            session.add_all(list(reversed(located)))
            session.add_all(
                [
                    Building(user_id=USER_ID, name="No coordinates"),
                    Building(
                        user_id=OTHER_USER_ID,
                        name="Other owner",
                        latitude=0,
                        longitude=0,
                    ),
                ]
            )
            await session.commit()
            session.expunge_all()
            statements: list[str] = []

            def record_statement(
                conn: object,
                cursor: object,
                statement: str,
                parameters: object,
                context: object,
                executemany: object,
            ) -> None:
                statements.append(statement)

            assert isinstance(session.bind, AsyncEngine)
            engine = session.bind.sync_engine
            event.listen(engine, "before_cursor_execute", record_statement)
            try:
                locations = await buildings.list_locations(user_id=USER_ID)
            finally:
                event.remove(engine, "before_cursor_execute", record_statement)

            assert [location.model_dump() for location in locations] == [
                {
                    "id": building.id,
                    "name": building.name,
                    "latitude": building.latitude,
                    "longitude": building.longitude,
                }
                for building in located
            ]
            assert len(statements) == 1
            assert "JOIN" not in statements[0].upper()
            assert "created_at" not in statements[0]
            assert "updated_at" not in statements[0]
            assert len(session.identity_map) == 0

    asyncio.run(run())


@pytest.mark.parametrize("status", list(ReconstructionStatus))
def test_latest_attempt_ignores_status_and_older_updates(
    status: ReconstructionStatus,
) -> None:
    async def run() -> None:
        async with building_service() as (buildings, session):
            building = await buildings.create(
                user_id=USER_ID, payload=BuildingCreate(name="Main building")
            )
            timestamp = datetime(2026, 9, 8, tzinfo=UTC)
            older = Reconstruction(
                id=UUID(int=300),
                building_id=building.id,
                settings={},
                created_at=timestamp - timedelta(days=1),
                status=ReconstructionStatus.RUNNING,
                progress=0.8,
            )
            tied = Reconstruction(
                id=UUID(int=100),
                building_id=building.id,
                settings={},
                created_at=timestamp,
                status=ReconstructionStatus.COMPLETED,
                progress=1,
            )
            latest = Reconstruction(
                id=UUID(int=200),
                building_id=building.id,
                settings={},
                created_at=timestamp,
                status=status,
                progress=0.456,
            )
            session.add_all([latest, older, tied])
            await session.commit()

            expected = {"id": latest.id, "status": status, "progress": 0.456}
            item = (await buildings.list(user_id=USER_ID))[0]
            assert item.latest_reconstruction is not None
            assert item.latest_reconstruction.model_dump() == expected
            processing = await buildings.list(
                user_id=USER_ID, reconstruction_status="processing", search="BUILD"
            )
            assert processing == [item]
            assert (
                await buildings.list(user_id=USER_ID, reconstruction_status="idle")
                == []
            )

            # An older attempt finishing later cannot displace the newest attempt.
            older.status = ReconstructionStatus.COMPLETED
            older.progress = 1
            older.updated_at = timestamp + timedelta(days=1)
            tied.updated_at = timestamp + timedelta(days=2)
            session.add_all([older, tied])
            await session.commit()
            item = (await buildings.list(user_id=USER_ID))[0]
            assert item.latest_reconstruction is not None
            assert item.latest_reconstruction.model_dump() == expected
            still_active = status in {
                ReconstructionStatus.PREPARING,
                ReconstructionStatus.SCHEDULED,
                ReconstructionStatus.RUNNING,
            }
            assert await buildings.list(
                user_id=USER_ID, reconstruction_status="processing"
            ) == ([item] if still_active else [])
            assert await buildings.list(
                user_id=USER_ID, reconstruction_status="idle"
            ) == ([] if still_active else [item])

    asyncio.run(run())


@pytest.mark.parametrize("reconstruction_status", [None, "processing", "idle"])
@pytest.mark.parametrize("search", [None, "1"])
def test_building_list_uses_one_query(
    reconstruction_status: ReconstructionStatusFilter | None,
    search: str | None,
) -> None:
    async def run() -> None:
        async with building_service() as (buildings, session):
            for index in range(3):
                building = await buildings.create(
                    user_id=USER_ID,
                    payload=BuildingCreate(name=str(index)),
                )
                session.add_all(
                    [
                        Reconstruction(building_id=building.id, settings={})
                        for _ in range(4)
                    ]
                )
            await session.commit()
            session.expunge_all()
            statements: list[str] = []

            def record_statement(
                conn: object,
                cursor: object,
                statement: str,
                parameters: object,
                context: object,
                executemany: object,
            ) -> None:
                statements.append(statement)

            assert isinstance(session.bind, AsyncEngine)
            engine = session.bind.sync_engine
            event.listen(engine, "before_cursor_execute", record_statement)
            try:
                items = await buildings.list(
                    user_id=USER_ID,
                    reconstruction_status=reconstruction_status,
                    search=search,
                )
                expected_count = 3 if search is None else 1
                assert len(items) == (
                    0 if reconstruction_status == "idle" else expected_count
                )
                assert all(item.latest_reconstruction is not None for item in items)
                assert len(statements) == 1
            finally:
                event.remove(engine, "before_cursor_execute", record_statement)

    asyncio.run(run())


@pytest.mark.parametrize("progress", [-0.01, 1.01])
def test_reconstruction_summary_validates_progress(progress: float) -> None:
    reconstruction = Reconstruction(
        building_id=UUID(int=1),
        settings={},
        progress=progress,
    )
    with pytest.raises(ValidationError):
        ReconstructionSummary.from_reconstruction(reconstruction)


def test_reconstruction_latest_index_matches_model() -> None:
    indexes = {
        index.name: [column.name for column in index.columns]
        for index in Reconstruction.__table__.indexes
    }
    assert indexes["ix_reconstructions_building_created_id"] == [
        "building_id",
        "created_at",
        "id",
    ]


@pytest.fixture
def api_client() -> Iterator[TestClient]:
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(User(id=USER_ID, keycloak_sub="subject-1"))
            await session.commit()

    asyncio.run(prepare_database())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app = FastAPI()
    app.include_router(building_views.router, prefix="/buildings")
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[require_user] = lambda: User(
        id=USER_ID,
        keycloak_sub="subject-1",
    )

    with TestClient(app) as client:
        yield client

    asyncio.run(engine.dispose())


def test_building_routes_cover_crud(api_client: TestClient) -> None:
    created_response = api_client.post(
        "/buildings",
        json={"name": "BC", "latitude": 46.518, "longitude": 6.563},
    )
    assert created_response.status_code == 201
    created = created_response.json()
    building_id = created["id"]
    assert created["user_id"] == str(USER_ID)
    assert created["name"] == "BC"
    assert datetime.fromisoformat(created["created_at"])

    list_response = api_client.get("/buildings?offset=0&limit=10")
    assert list_response.status_code == 200
    assert list_response.json() == [{**created, "latest_reconstruction": None}]
    assert (
        api_client.get("/buildings?reconstruction_status=idle").json()
        == list_response.json()
    )
    assert api_client.get("/buildings?reconstruction_status=processing").json() == []
    assert "latest_reconstruction" not in created

    get_response = api_client.get(f"/buildings/{building_id}")
    assert get_response.status_code == 200
    assert get_response.json() == created

    update_response = api_client.patch(
        f"/buildings/{building_id}",
        json={"name": "", "latitude": None, "longitude": None},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == ""
    assert update_response.json()["latitude"] is None
    assert update_response.json()["longitude"] is None
    assert "latest_reconstruction" not in update_response.json()

    delete_response = api_client.delete(f"/buildings/{building_id}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert api_client.get(f"/buildings/{building_id}").status_code == 404


@pytest.mark.parametrize(
    "metadata", [{}, {"address": None}, {"address": "Route de la Sorge 1"}]
)
def test_building_address_persists_and_can_be_cleared(
    api_client: TestClient, metadata: dict[str, object]
) -> None:
    response = api_client.post("/buildings", json=metadata)
    assert response.status_code == 201
    building = response.json()
    path = f"/buildings/{building['id']}"
    assert building["address"] == metadata.get("address")
    assert api_client.get(path).json()["address"] == metadata.get("address")
    assert api_client.get("/buildings").json()[0]["address"] == metadata.get("address")

    updated = api_client.patch(path, json={"address": "Avenue Piccard 12"})
    assert updated.status_code == 200
    assert updated.json()["address"] == "Avenue Piccard 12"
    assert updated.json()["updated_at"] != building["updated_at"]
    assert api_client.get(path).json()["address"] == "Avenue Piccard 12"
    assert api_client.get("/buildings").json()[0]["address"] == "Avenue Piccard 12"

    renamed = api_client.patch(path, json={"name": "New name"})
    assert renamed.status_code == 200
    assert renamed.json()["address"] == "Avenue Piccard 12"
    unchanged = api_client.patch(path, json={"address": "Avenue Piccard 12"})
    assert unchanged.json()["updated_at"] == renamed.json()["updated_at"]

    cleared = api_client.patch(path, json={"address": None})
    assert cleared.status_code == 200
    assert cleared.json()["address"] is None
    assert cleared.json()["name"] == "New name"
    assert api_client.get(path).json()["address"] is None
    assert api_client.get("/buildings").json()[0]["address"] is None


def test_building_locations_route_filters_and_serializes(
    api_client: TestClient,
) -> None:
    # A static route must not be mistaken for the UUID detail route.
    response = api_client.get("/buildings/locations")
    assert response.status_code == 200
    assert response.json() == []
    api_client.post("/buildings", json={"name": "No location"})
    created = api_client.post(
        "/buildings",
        json={"name": "", "latitude": 0, "longitude": 0},
    ).json()
    assert api_client.get("/buildings/locations").json() == [
        {
            "id": created["id"],
            "name": "",
            "latitude": 0,
            "longitude": 0,
        }
    ]

    original_override = api_client.app.dependency_overrides[require_user]
    api_client.app.dependency_overrides[require_user] = lambda: User(
        id=OTHER_USER_ID,
        keycloak_sub="subject-2",
    )
    try:
        assert api_client.get("/buildings/locations").json() == []
    finally:
        api_client.app.dependency_overrides[require_user] = original_override


def test_building_locations_route_maps_database_failures(
    api_client: TestClient,
) -> None:
    class FailingBuildingService(BuildingService):
        def __init__(self) -> None:
            pass

        async def list_locations(self, *, user_id: UUID) -> list[BuildingLocationRead]:
            raise OperationalError("SELECT", {}, RuntimeError("offline"))

    api_client.app.dependency_overrides[building_views.get_building_service] = (
        FailingBuildingService
    )
    response = api_client.get("/buildings/locations")
    assert response.status_code == 503
    assert response.json() == {"detail": "Building database is unavailable"}


def test_building_routes_validate_payload_and_pagination(
    api_client: TestClient,
) -> None:
    assert (
        api_client.post(
            "/buildings",
            json={"name": "", "latitude": 91, "longitude": 0},
        ).status_code
        == 422
    )
    assert api_client.post("/buildings", json={"latitude": 46}).status_code == 422
    building_id = api_client.post("/buildings", json={}).json()["id"]
    assert (
        api_client.patch(
            f"/buildings/{building_id}",
            json={"latitude": None},
        ).status_code
        == 422
    )
    assert api_client.get("/buildings?offset=-1").status_code == 422
    assert api_client.get("/buildings?limit=101").status_code == 422
    assert api_client.get("/buildings?sort_order=invalid").status_code == 422
    for value in ("running", "all", "null", "", "true"):
        response = api_client.get("/buildings", params={"reconstruction_status": value})
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["query", "reconstruction_status"]


def test_building_routes_search_names(api_client: TestClient) -> None:
    names = [
        "Main Hall",
        "HALLway Building",
        "Hall  Annex",
        "",
        "100% complete",
        "100X complete",
        "Wing_A",
        "WingXA",
        "North/Wing",
        "North\\Wing",
        "O'Brien & Sons + Annex #1?",
        "École",
        "Literal /%_ signs",
    ]
    created = [
        api_client.post("/buildings", json={"name": name}).json() for name in names
    ]
    cases = [
        (None, names),
        ("", names),
        (" \t\n ", names),
        ("hall", names[:3]),
        ("  hAlL\t", names[:3]),
        ("allw", ["HALLway Building"]),
        ("Hall  Annex", ["Hall  Annex"]),
        ("Hall Annex", []),
        ("Untitled building", []),
        ("missing", []),
        ("%", ["100% complete", "Literal /%_ signs"]),
        ("_", ["Wing_A", "Literal /%_ signs"]),
        ("/", ["North/Wing", "Literal /%_ signs"]),
        ("/%_", ["Literal /%_ signs"]),
        ("\\", ["North\\Wing"]),
        ("O'Brien & Sons + Annex #1?", ["O'Brien & Sons + Annex #1?"]),
        ("École", ["École"]),
        ("' OR 1=1 --", []),
    ]
    for search, matching_names in cases:
        params = {"sort_order": "asc"}
        if search is not None:
            params["search"] = search
        response = api_client.get("/buildings", params=params)
        assert response.status_code == 200
        assert response.json() == [
            {**building, "latest_reconstruction": None}
            for building in created
            if building["name"] in matching_names
        ], search


def test_building_routes_support_sort_order(api_client: TestClient) -> None:
    first = api_client.post("/buildings", json={"name": "First"}).json()
    second = api_client.post("/buildings", json={"name": "Second"}).json()
    first = {**first, "latest_reconstruction": None}
    second = {**second, "latest_reconstruction": None}

    assert api_client.get("/buildings").json() == [second, first]
    assert api_client.get("/buildings?sort_order=desc").json() == [second, first]
    assert api_client.get("/buildings?sort_order=asc").json() == [first, second]
    assert api_client.get("/buildings?sort_order=desc&offset=1&limit=1").json() == [
        first
    ]


@pytest.mark.parametrize("status", list(ReconstructionStatus))
def test_building_routes_return_reconstruction_summary(
    api_client: TestClient,
    status: ReconstructionStatus,
) -> None:
    created = api_client.post("/buildings", json={"name": "With reconstruction"}).json()
    reconstruction_id = UUID(int=500)

    async def insert_reconstruction() -> None:
        async for session in api_client.app.dependency_overrides[get_session]():
            session.add(
                Reconstruction(
                    id=reconstruction_id,
                    building_id=UUID(created["id"]),
                    settings={},
                    status=status,
                    progress=0.375,
                )
            )
            await session.commit()

    asyncio.run(insert_reconstruction())
    response = api_client.get("/buildings")
    assert response.status_code == 200
    assert response.json() == [
        {
            **created,
            "latest_reconstruction": {
                "id": str(reconstruction_id),
                "status": status.value,
                "progress": 0.375,
            },
        }
    ]
    assert api_client.get(f"/buildings/{created['id']}").json() == created
    active = status in {
        ReconstructionStatus.PREPARING,
        ReconstructionStatus.SCHEDULED,
        ReconstructionStatus.RUNNING,
    }
    for filter_value, matches in (("processing", active), ("idle", not active)):
        filtered = api_client.get(
            "/buildings", params={"reconstruction_status": filter_value}
        )
        assert filtered.status_code == 200
        assert filtered.json() == (response.json() if matches else [])


def test_building_routes_hide_rows_owned_by_another_user(
    api_client: TestClient,
) -> None:
    created = api_client.post(
        "/buildings",
        json={"name": "BC", "latitude": 46.518, "longitude": 6.563},
    ).json()

    original_override = api_client.app.dependency_overrides[require_user]
    api_client.app.dependency_overrides[require_user] = lambda: User(
        id=OTHER_USER_ID,
        keycloak_sub="subject-2",
    )
    try:
        assert api_client.get("/buildings?sort_order=desc").json() == []
        assert api_client.get("/buildings?sort_order=asc").json() == []
        assert api_client.get(f"/buildings/{created['id']}").status_code == 404
        assert (
            api_client.patch(
                f"/buildings/{created['id']}", json={"name": "stolen"}
            ).status_code
            == 404
        )
        assert api_client.delete(f"/buildings/{created['id']}").status_code == 404
    finally:
        api_client.app.dependency_overrides[require_user] = original_override


def test_building_routes_map_database_failures_to_503(
    api_client: TestClient,
) -> None:
    class FailingBuildingService(BuildingService):
        def __init__(self) -> None:
            pass

        async def list(self, **kwargs: object) -> list[BuildingListItemRead]:
            raise OperationalError("SELECT", {}, RuntimeError("offline"))

    api_client.app.dependency_overrides[building_views.get_building_service] = (
        FailingBuildingService
    )
    response = api_client.get("/buildings")

    assert response.status_code == 503
    assert response.json() == {"detail": "Building database is unavailable"}
