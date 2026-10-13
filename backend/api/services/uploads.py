from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.uploads import UserUploadCreate, UserUploads, UserUploadUpdate

SortOrder = Literal["asc", "desc"]


class UserUploadsService:
    """Create, query, update, and delete user-owned upload metadata."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: UUID,
        payload: UserUploadCreate,
        filename: str,
        size_bytes: int,
        file_path: str,
    ) -> UserUploads:
        upload = UserUploads(
            user_id=user_id,
            filename=filename,
            size_bytes=size_bytes,
            file_path=file_path,
            **payload.model_dump(),
        )
        self._session.add(upload)
        await self._commit_and_refresh(upload)
        return upload

    async def get(
        self,
        upload_id: UUID,
        *,
        user_id: UUID,
    ) -> UserUploads | None:
        result = await self._session.exec(
            select(UserUploads).where(
                UserUploads.id == upload_id,
                UserUploads.user_id == user_id,
            )
        )
        return result.first()

    async def list(
        self,
        *,
        user_id: UUID,
        offset: int = 0,
        limit: int = 100,
        sort_order: SortOrder = "desc",
    ) -> list[UserUploads]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if sort_order not in ("asc", "desc"):
            raise ValueError("sort_order must be asc or desc")

        ordering = (
            (col(UserUploads.created_at).asc(), col(UserUploads.id).asc())
            if sort_order == "asc"
            else (col(UserUploads.created_at).desc(), col(UserUploads.id).desc())
        )
        result = await self._session.exec(
            select(UserUploads)
            .where(UserUploads.user_id == user_id)
            .order_by(*ordering)
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def update(
        self,
        upload: UserUploads,
        payload: UserUploadUpdate,
    ) -> UserUploads:
        changes = payload.model_dump(exclude_unset=True)
        if not any(
            getattr(upload, field_name) != value
            for field_name, value in changes.items()
        ):
            return upload

        for field_name, value in changes.items():
            setattr(upload, field_name, value)

        self._session.add(upload)
        await self._commit_and_refresh(upload)
        return upload

    async def delete(self, upload: UserUploads) -> None:
        try:
            await self._session.delete(upload)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def _commit_and_refresh(self, upload: UserUploads) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(upload)
