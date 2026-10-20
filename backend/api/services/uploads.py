from __future__ import annotations

import builtins
import logging
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.lib.upload_storage import (
    copy_completed_file,
    remove_tus_files,
    upload_file_path,
    validate_completed_file,
)
from api.models.reconstruction import Reconstruction, ReconstructionStatus
from api.models.uploads import (
    UploadStatus,
    UserUploadCreate,
    UserUploads,
    UserUploadUpdate,
)
from api.models.user import utc_now
from api.services.reconstructions import ReconstructionService

SortOrder = Literal["asc", "desc"]
logger = logging.getLogger(__name__)


class UploadNotFoundError(Exception):
    pass


class UploadConflictError(Exception):
    pass


class UserUploadsService:
    """Manage user-owned upload metadata and completed-file persistence."""

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
        for field_name in ("user_id", "filename", "size_bytes"):
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
        status: UploadStatus | None = None,
    ) -> builtins.list[UserUploads]:
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
        query = select(UserUploads).where(UserUploads.user_id == user_id)
        if status is not None:
            query = query.where(UserUploads.status == status)
        result = await self._session.exec(
            query.order_by(*ordering).offset(offset).limit(limit)
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

    async def update_progress(
        self,
        upload_id: UUID,
        *,
        uploaded_bytes: int,
    ) -> None:
        """Record increasing progress without racing upload completion."""

        try:
            upload = await self._get_for_update(upload_id)
            if not 0 <= uploaded_bytes <= upload.size_bytes:
                raise UploadConflictError("Upload progress is outside the file size")
            if (
                upload.status == UploadStatus.PENDING
                and uploaded_bytes > upload.uploaded_bytes
            ):
                upload.uploaded_bytes = uploaded_bytes
                self._session.add(upload)
            # Also release the row lock when the event did not advance progress.
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

    async def complete(self, upload_id: UUID) -> UserUploads:
        """Persist completed bytes, then dispatch reconstructions awaiting them."""

        try:
            upload = await self._get_for_update(upload_id)
            if upload.status not in (UploadStatus.PENDING, UploadStatus.UPLOADED):
                raise UploadConflictError("Upload cannot be completed")

            destination = upload_file_path(upload.id, upload.filename).resolve()
            await run_in_threadpool(
                copy_completed_file,
                Path(upload.file_path),
                destination,
                upload.size_bytes,
            )

            upload.file_path = str(destination)
            upload.uploaded_bytes = upload.size_bytes
            upload.status = UploadStatus.UPLOADED
            if upload.uploaded_at is None:
                upload.uploaded_at = utc_now()
            self._session.add(upload)
            await self._session.flush()
            await self._session.refresh(upload)
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

        # Never remove the recoverable staging copy before the DB commit.
        try:
            remove_tus_files(upload_id)
        except OSError:
            logger.exception("Could not remove staging files for upload %s", upload_id)

        await ReconstructionService(self._session).schedule_waiting_for_upload(
            upload_id
        )
        return upload

    async def get_completed(
        self,
        upload_id: UUID,
        *,
        user_id: UUID,
    ) -> UserUploads:
        upload = await self.get(upload_id, user_id=user_id)
        if upload is None:
            raise UploadNotFoundError("Upload not found")
        self.require_uploaded(upload)
        validate_completed_file(Path(upload.file_path), upload.size_bytes)
        return upload

    def require_uploaded(self, upload: UserUploads) -> None:
        if upload.status != UploadStatus.UPLOADED:
            raise UploadConflictError("Upload has not finished uploading")

    async def delete(self, upload_id: UUID) -> None:
        try:
            upload = await self._get_for_update(upload_id)
            self.require_uploaded(upload)
            waiting_id = await self._session.scalar(
                select(Reconstruction.id)
                .where(
                    Reconstruction.upload_id == upload.id,
                    Reconstruction.status == ReconstructionStatus.WAITING_FOR_UPLOAD,
                )
                .limit(1)
            )
            if waiting_id is not None:
                raise UploadConflictError("Reconstructions are waiting for this upload")
            await self._session.delete(upload)
            await self._session.commit()
        except BaseException:
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
        except BaseException:
            await self._session.rollback()
            raise
        await self._session.refresh(upload)
