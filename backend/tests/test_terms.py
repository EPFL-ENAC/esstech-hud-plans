import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.config import config
from api.db import get_session
from api.models.auth import AuthenticatedUser
from api.models.user import User
from api.services.auth import authenticate_user
from api.services.terms import is_accepted, terms_content
from api.views import buildings as building_views
from api.views import terms as term_views
from api.views import users as user_views


@asynccontextmanager
async def terms_client() -> AsyncIterator[tuple[TestClient, AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)

        session = AsyncSession(engine, expire_on_commit=False)

        async def session_override() -> AsyncIterator[AsyncSession]:
            yield session

        app = FastAPI()
        app.include_router(term_views.router, prefix="/terms")
        app.include_router(building_views.router, prefix="/buildings")
        app.include_router(user_views.router, prefix="/user")
        app.dependency_overrides[get_session] = session_override
        app.dependency_overrides[authenticate_user] = lambda: AuthenticatedUser(
            sub="subject-1", username="tester"
        )

        with TestClient(app) as client:
            yield client, session
        await session.close()
    finally:
        await engine.dispose()


def test_terms_route_returns_version_and_all_locales() -> None:
    async def run() -> None:
        async with terms_client() as (client, _):
            response = client.get("/terms")

        assert response.status_code == 200
        payload = response.json()
        assert payload["version"] == config.TERMS_VERSION
        expected = terms_content()
        assert set(payload["content"]) == {"en", "fr", "es"}
        for locale in ("en", "fr", "es"):
            assert payload["content"][locale] == expected[locale]

    asyncio.run(run())


def test_gated_endpoint_rejects_before_acceptance() -> None:
    async def run() -> None:
        async with terms_client() as (client, session):
            response = client.get("/buildings")

        assert response.status_code == 403
        assert response.json() == {"detail": "terms_not_accepted"}

    asyncio.run(run())


def test_accept_route_sets_columns_and_is_idempotent() -> None:
    async def run() -> None:
        async with terms_client() as (client, session):
            first = client.post("/terms/accept")
            assert first.status_code == 200
            payload = first.json()
            assert payload["terms_accepted"] is True
            assert payload["terms_accepted_version"] == config.TERMS_VERSION
            accepted_at = datetime.fromisoformat(payload["terms_accepted_at"])

            user = (
                await session.exec(select(User).where(User.keycloak_sub == "subject-1"))
            ).one()
            assert user is not None
            assert user.terms_accepted_version == config.TERMS_VERSION
            assert user.terms_accepted_at == accepted_at

            second = client.post("/terms/accept")
            assert second.status_code == 200
            assert second.json()["terms_accepted_at"] == payload["terms_accepted_at"]
            await session.refresh(user)
            assert user.terms_accepted_at == accepted_at

    asyncio.run(run())


def test_me_route_reports_accepted_after_accept() -> None:
    async def run() -> None:
        async with terms_client() as (client, _):
            before = client.get("/user/me").json()
            assert before["terms_accepted"] is False

            client.post("/terms/accept")

            after = client.get("/user/me").json()
        assert after["terms_accepted"] is True
        assert after["terms_accepted_version"] == config.TERMS_VERSION
        assert datetime.fromisoformat(after["terms_accepted_at"])

    asyncio.run(run())


def test_is_accepted_requires_current_version() -> None:
    assert is_accepted(User(terms_accepted_version="v1")) is True
    assert is_accepted(User(terms_accepted_version="v0")) is False
    assert is_accepted(User()) is False
