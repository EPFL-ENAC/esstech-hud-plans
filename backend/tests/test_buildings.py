import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

import pytest
from api.db import get_session
from api.models.building import Building, BuildingCreate, BuildingRead, BuildingUpdate
from api.models.user import User
from api.services.auth import require_user
from api.services.buildings import BuildingService
from api.views import buildings as building_views
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ValidationError
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
    assert Building.__tablename__ == "buildings"
    assert User.__mapper__.relationships["buildings"].back_populates == "user"
    assert Building.__mapper__.relationships["user"].back_populates == "buildings"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "", "latitude": 46.52, "longitude": 6.57},
        {"name": "EPFL", "latitude": -90.01, "longitude": 6.57},
        {"name": "EPFL", "latitude": 90.01, "longitude": 6.57},
        {"name": "EPFL", "latitude": 46.52, "longitude": -180.01},
        {"name": "EPFL", "latitude": 46.52, "longitude": 180.01},
    ],
)
def test_building_create_validates_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BuildingCreate.model_validate(payload)


@pytest.mark.parametrize("field_name", ["name", "latitude", "longitude"])
def test_building_update_rejects_explicit_nulls(field_name: str) -> None:
    with pytest.raises(ValidationError):
        BuildingUpdate.model_validate({field_name: None})


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
            assert await buildings.list(user_id=USER_ID) == [first, duplicate_name]
            assert await buildings.list(user_id=OTHER_USER_ID) == [other_user_building]
            assert await buildings.list(user_id=USER_ID, offset=1, limit=1) == [
                duplicate_name
            ]

            original_updated_at = first.updated_at
            unchanged = await buildings.update(first, BuildingUpdate())
            assert unchanged.updated_at == original_updated_at

            updated = await buildings.update(
                first,
                BuildingUpdate(name="Renamed", latitude=46.6),
            )
            assert updated.name == "Renamed"
            assert updated.latitude == 46.6
            assert updated.longitude == 6.5668
            assert updated.updated_at > original_updated_at

            await buildings.delete(updated)
            assert await buildings.get(first.id, user_id=USER_ID) is None
            assert (await session.exec(select(Building))).all() == [
                duplicate_name,
                other_user_building,
            ]

    asyncio.run(run())


def test_building_list_validates_pagination() -> None:
    async def run() -> None:
        async with building_service() as (buildings, _):
            for kwargs in ({"offset": -1}, {"limit": 0}, {"limit": 101}):
                with pytest.raises(ValueError):
                    await buildings.list(user_id=USER_ID, **kwargs)

    asyncio.run(run())


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
    assert list_response.json() == [created]

    get_response = api_client.get(f"/buildings/{building_id}")
    assert get_response.status_code == 200
    assert get_response.json() == created

    update_response = api_client.patch(
        f"/buildings/{building_id}",
        json={"name": "BC renamed", "longitude": 6.564},
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "BC renamed"
    assert update_response.json()["latitude"] == 46.518
    assert update_response.json()["longitude"] == 6.564

    delete_response = api_client.delete(f"/buildings/{building_id}")
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert api_client.get(f"/buildings/{building_id}").status_code == 404


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
    assert api_client.get("/buildings?offset=-1").status_code == 422
    assert api_client.get("/buildings?limit=101").status_code == 422


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

        async def list(self, **kwargs: object) -> list[Building]:
            raise OperationalError("SELECT", {}, RuntimeError("offline"))

    api_client.app.dependency_overrides[building_views.get_building_service] = (
        FailingBuildingService
    )
    response = api_client.get("/buildings")

    assert response.status_code == 503
    assert response.json() == {"detail": "Building database is unavailable"}
