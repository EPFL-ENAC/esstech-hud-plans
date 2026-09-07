import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from api.models.auth import AuthenticatedUser
from api.models.user import User, UserCreate, UserUpdate
from api.services.users import UserService
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


@asynccontextmanager
async def user_service() -> AsyncIterator[UserService]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield UserService(session)
    finally:
        await engine.dispose()


def test_only_database_user_inherits_from_sqlmodel() -> None:
    assert issubclass(UserCreate, BaseModel)
    assert issubclass(UserUpdate, BaseModel)
    assert not issubclass(UserCreate, SQLModel)
    assert not issubclass(UserUpdate, SQLModel)
    assert User.__tablename__ == "users"


def test_create_get_and_list_users() -> None:
    async def run() -> None:
        async with user_service() as users:
            first = await users.create(
                UserCreate(keycloak_sub="subject-1", username="first")
            )
            second = await users.create(
                UserCreate(keycloak_sub="subject-2", username="second")
            )

            assert await users.get(first.id) == first
            assert await users.get_by_keycloak_sub("subject-2") == second
            assert await users.get_by_keycloak_sub("missing") is None
            assert await users.list(offset=0, limit=1) == [first]
            assert await users.list(offset=1, limit=1) == [second]

    asyncio.run(run())


def test_list_users_validates_pagination() -> None:
    async def run() -> None:
        async with user_service() as users:
            for kwargs in ({"offset": -1}, {"limit": 0}, {"limit": 101}):
                try:
                    await users.list(**kwargs)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Expected invalid pagination to fail")

    asyncio.run(run())


def test_update_supports_partial_changes_and_explicit_nulls() -> None:
    async def run() -> None:
        async with user_service() as users:
            user = await users.create(
                UserCreate(
                    keycloak_sub="subject-1",
                    username="before",
                    email="user@example.com",
                )
            )
            original_created_at = user.created_at
            original_updated_at = user.updated_at

            unchanged = await users.update(user, UserUpdate())
            assert unchanged.updated_at == original_updated_at

            updated = await users.update(
                user,
                UserUpdate(username="after", email=None),
            )
            assert updated.username == "after"
            assert updated.email is None
            assert updated.created_at == original_created_at
            assert updated.updated_at > original_updated_at

    asyncio.run(run())


def test_sync_authenticated_user_creates_then_refreshes_identity() -> None:
    async def run() -> None:
        async with user_service() as users:
            user = await users.sync_authenticated_user(
                AuthenticatedUser(
                    sub="subject-1",
                    username="before",
                    email="before@example.com",
                )
            )
            original_id = user.id
            original_created_at = user.created_at

            refreshed = await users.sync_authenticated_user(
                AuthenticatedUser(
                    sub="subject-1",
                    username="after",
                    email="after@example.com",
                    name="Example User",
                )
            )

            assert refreshed.id == original_id
            assert refreshed.keycloak_sub == "subject-1"
            assert refreshed.created_at == original_created_at
            assert refreshed.username == "after"
            assert refreshed.email == "after@example.com"
            assert refreshed.name == "Example User"
            assert len(await users.list()) == 1

    asyncio.run(run())


def test_sync_authenticated_user_recovers_from_create_race() -> None:
    winner = User(
        id=uuid4(),
        keycloak_sub="subject-1",
        username="winner",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    class RacingUserService(UserService):
        def __init__(self) -> None:
            self.lookup_count = 0

        async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
            assert keycloak_sub == "subject-1"
            self.lookup_count += 1
            return None if self.lookup_count == 1 else winner

        async def create(self, payload: UserCreate) -> User:
            raise IntegrityError("INSERT", {}, RuntimeError("duplicate"))

        async def update(self, user: User, payload: UserUpdate) -> User:
            assert user is winner
            user.username = payload.username
            return user

    async def run() -> None:
        users = RacingUserService()
        result = await users.sync_authenticated_user(
            AuthenticatedUser(sub="subject-1", username="latest")
        )
        assert result is winner
        assert result.username == "latest"

    asyncio.run(run())
