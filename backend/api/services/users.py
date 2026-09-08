from __future__ import annotations

from uuid import UUID

from api.db import retry_on_db_error
from api.models.auth import AuthenticatedUser
from api.models.user import User, UserCreate, UserUpdate, utc_now
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession


class UserService:
    """Create, query, and update application user rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_keycloak_sub(self, keycloak_sub: str) -> User | None:
        result = await self._session.exec(
            select(User).where(User.keycloak_sub == keycloak_sub)
        )
        return result.first()

    async def list(self, *, offset: int = 0, limit: int = 100) -> list[User]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        result = await self._session.exec(
            select(User)
            .order_by(col(User.created_at), col(User.id))
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def create(self, payload: UserCreate) -> User:
        user = User(**payload.model_dump())
        self._session.add(user)
        await self._commit_and_refresh(user)
        return user

    async def update(self, user: User, payload: UserUpdate) -> User:
        changes = payload.model_dump(exclude_unset=True)
        changed = any(
            getattr(user, field_name) != value for field_name, value in changes.items()
        )
        if not changed:
            return user

        for field_name, value in changes.items():
            setattr(user, field_name, value)

        user.updated_at = utc_now()
        self._session.add(user)
        await self._commit_and_refresh(user)
        return user

    async def sync_authenticated_user(self, identity: AuthenticatedUser) -> User:
        """Create or refresh the user matching a verified identity."""

        async def operation() -> User:
            try:
                return await self._sync_authenticated_user_once(identity)
            except (OSError, OperationalError):
                await self._session.rollback()
                raise

        return await retry_on_db_error(
            operation,
            operation_name="User synchronization",
        )

    async def _sync_authenticated_user_once(self, identity: AuthenticatedUser) -> User:
        user = await self.get_by_keycloak_sub(identity.sub)
        if user is None:
            try:
                return await self.create(
                    UserCreate(
                        keycloak_sub=identity.sub,
                        username=identity.username,
                        email=identity.email,
                        name=identity.name,
                    )
                )
            except IntegrityError:
                # A concurrent first request may have created the same user.
                user = await self.get_by_keycloak_sub(identity.sub)
                if user is None:
                    raise

        return await self.update(
            user,
            UserUpdate(
                username=identity.username,
                email=identity.email,
                name=identity.name,
            ),
        )

    async def _commit_and_refresh(self, user: User) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(user)
