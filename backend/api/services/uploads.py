from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.uploads import (
    UploadStatus,
    UserUploadCreate,
    UserUploads,
    UserUploadUpdate,
)
from api.models.user import utc_now

SortOrder = Literal["asc", "desc"]


class UploadNotFoundError(Exception):
    pass


class UploadConflictError(Exception):
    pass


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
        upload_id: UUID | None = None,
    ) -> UserUploads:
        upload = UserUploads(
            id=upload_id or uuid4(),
            user_id=user_id,
            filename=filename,
            size_bytes=size_bytes,
            file_path=file_path,
            **payload.model_dump(),
        )
        if upload_id is not None:
            existing = await self._session.get(UserUploads, upload_id)
            if existing is not None:
                return self._reuse_upload(existing, upload)

        self._session.add(upload)
        try:
            await self._commit_and_refresh(upload)
        except IntegrityError:
            # The commit helper rolled back. Another delivery may have inserted
            # the same ID after our initial lookup; only reuse a matching row.
            if upload_id is None:
                raise
            existing = await self._session.get(UserUploads, upload_id)
            if existing is None:
                raise
            return self._reuse_upload(existing, upload)
        return upload

    def _reuse_upload(
        self,
        existing: UserUploads,
        candidate: UserUploads,
    ) -> UserUploads:
        for field_name in ("user_id", "filename", "size_bytes", "file_path"):
            if getattr(existing, field_name) != getattr(candidate, field_name):
                raise UploadConflictError(
                    "Upload ID is already registered with different metadata"
                )
        return existing

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

    async def mark_uploaded(self, upload_id: UUID) -> UserUploads:
        """Complete an upload once, preserving its first completion timestamp."""

        try:
            upload = await self._get_for_update(upload_id)
            if upload.status == UploadStatus.UPLOADED:
                await self._session.commit()
                return upload
            if upload.status != UploadStatus.PENDING:
                raise UploadConflictError("Upload is not pending")

            upload.status = UploadStatus.UPLOADED
            upload.uploaded_at = utc_now()
            self._session.add(upload)
            await self._commit_and_refresh(upload)
            return upload
        except Exception:
            await self._session.rollback()
            raise

    def require_uploaded(self, upload: UserUploads) -> None:
        if upload.status != UploadStatus.UPLOADED:
            raise UploadConflictError("Upload has not finished uploading")

    async def delete(self, upload: UserUploads) -> None:
        self.require_uploaded(upload)
        try:
            await self._session.delete(upload)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def _get_for_update(self, upload_id: UUID) -> UserUploads:
        result = await self._session.exec(
            select(UserUploads)
            .where(UserUploads.id == upload_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        upload = result.first()
        if upload is None:
            raise UploadNotFoundError("Upload not found")
        return upload

    async def _commit_and_refresh(self, upload: UserUploads) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(upload)
