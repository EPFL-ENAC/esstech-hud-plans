"""Chunked video upload sessions and their finalization."""

from __future__ import annotations

import logging
import math
import mimetypes
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import time
from uuid import UUID

from api.config import config
from api.lib.uploads import paths
from api.models.building import (
    Building,
    BuildingCreate,
    BuildingFromReconstructionRead,
    BuildingRead,
)
from api.models.reconstruction import ReconstructionRead
from api.models.uploads import (
    ChunkPutResult,
    UploadChunk,
    UploadSession,
    UploadSessionCreate,
    UploadSessionState,
    UploadSessionStatus,
)
from api.models.user import utc_now
from api.models.workflows import SplatGenerationWorkflowSettings
from api.services.buildings import BuildingService
from api.services.reconstructions import (
    ReconstructionCreationError,
    ReconstructionService,
)
from sqlalchemy import delete, func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

ORPHAN_TEMP_GRACE_SECONDS = 3600

FinalizeResponse = ReconstructionRead | BuildingFromReconstructionRead


class UploadSessionNotFoundError(Exception):
    pass


class UploadSessionExpiredError(Exception):
    pass


class UploadSessionFinalizedError(Exception):
    pass


class UploadChunkNotFoundError(Exception):
    pass


class UploadSessionNotCompleteError(Exception):
    """Raised while chunk bytes or part files are still missing."""

    def __init__(self, missing_chunks: list[int]) -> None:
        super().__init__(f"Upload session is missing chunks {missing_chunks}")
        self.missing_chunks = missing_chunks


class UploadAssemblyError(Exception):
    """Raised when the staged chunks cannot form the declared video."""


class UploadFinalizationError(Exception):
    """Reconstruction submission failed after finalization started."""

    def __init__(
        self,
        message: str,
        *,
        reconstruction_id: UUID,
        building_id: UUID | None,
    ) -> None:
        super().__init__(message)
        self.reconstruction_id = reconstruction_id
        self.building_id = building_id


def _uuid_from_hex(name: str) -> UUID | None:
    try:
        return UUID(hex=name)
    except ValueError:
        return None


def build_chunk_rows(
    payload: UploadSessionCreate,
    *,
    chunk_size: int,
) -> list[UploadChunk]:
    """Validate the declared chunk plan and build its session rows.

    The last chunk may be smaller than the configured chunk size. The client
    chunk plan must cover the declared total size exactly once. Rows carry a
    placeholder session id until the caller assigns the persisted session.
    """
    total_chunks = math.ceil(payload.total_size / chunk_size)
    entries = sorted(payload.chunks, key=lambda entry: entry.index)
    if [entry.index for entry in entries] != list(range(total_chunks)):
        raise ValueError(
            f"Chunk plan must contain {total_chunks} chunks with indexes "
            f"0..{total_chunks - 1}"
        )

    rows: list[UploadChunk] = []
    for entry in entries:
        byte_offset = entry.index * chunk_size
        expected_size = min(chunk_size, payload.total_size - byte_offset)
        if entry.size != expected_size:
            raise ValueError(f"Chunk {entry.index} must hold {expected_size} bytes")
        rows.append(
            UploadChunk(
                session_id=UUID(int=0),
                chunk_index=entry.index,
                byte_offset=byte_offset,
                expected_size=expected_size,
                expected_digest=entry.sha256,
            )
        )
    return rows


class UploadService:
    """Persist chunked upload sessions and drive their finalization."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- session lifecycle --

    async def create_session(
        self,
        *,
        user_id: UUID,
        payload: UploadSessionCreate,
        building: Building | None,
    ) -> UploadSession:
        """Persist one upload session and its pre-declared chunk rows."""

        filename = Path(payload.filename).name
        if not filename:
            raise ValueError("File must have a filename")
        file_extension = Path(filename).suffix.removeprefix(".").lower() or "mp4"
        media_type = mimetypes.guess_type(f"video.{file_extension}")[0]
        if media_type is None or not media_type.startswith("video/"):
            raise ValueError("Uploaded file must be a video")

        chunk_size = config.UPLOAD_CHUNK_SIZE_BYTES
        chunk_rows = build_chunk_rows(payload, chunk_size=chunk_size)

        session_row = UploadSession(
            user_id=user_id,
            building_id=building.id if building is not None else None,
            building_payload=payload.building,
            settings=payload.settings.model_dump(mode="json"),
            filename=filename,
            file_extension=file_extension,
            total_size=payload.total_size,
            chunk_size=chunk_size,
            total_chunks=len(chunk_rows),
            received_bytes=0,
            expires_at=(utc_now() + timedelta(hours=config.UPLOAD_SESSION_TTL_HOURS)),
        )
        self._session.add(session_row)
        await self._commit_and_refresh(session_row)

        for row in chunk_rows:
            row.session_id = session_row.id
        self._session.add_all(chunk_rows)
        try:
            await self._session.commit()
        except SQLAlchemyError:
            await self._session.rollback()
            # Best effort orphan cleanup: the session row must not survive
            # without its chunk plan, because the client cannot resume it.
            try:
                await self._session.execute(
                    delete(UploadSession).where(UploadSession.id == session_row.id)
                )
                await self._session.commit()
            except SQLAlchemyError:
                await self._session.rollback()
            raise
        await self._session.refresh(session_row)
        return session_row

    async def get_owned_session(
        self,
        session_id: UUID,
        *,
        user_id: UUID,
    ) -> UploadSession:
        session_row = await self._session.get(UploadSession, session_id)
        if session_row is None or session_row.user_id != user_id:
            raise UploadSessionNotFoundError
        await self._session.refresh(session_row)
        return session_row

    @staticmethod
    def assert_not_expired(session_row: UploadSession) -> None:
        expires_at = session_row.expires_at
        # SQLite test engines return naive datetimes; Postgres returns aware ones.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= utc_now():
            raise UploadSessionExpiredError

    async def delete_session(self, session_row: UploadSession) -> None:
        """Remove the staging directory and the session rows."""

        await run_in_threadpool(shutil.rmtree, paths.session_dir(session_row.id), True)
        await self._session.exec(
            delete(UploadChunk).where(UploadChunk.session_id == session_row.id)
        )
        await self._session.delete(session_row)
        await self._session.commit()

    async def state_for(self, session_row: UploadSession) -> UploadSessionState:
        missing = await self.missing_chunks(session_row.id)
        return UploadSessionState(
            session_id=session_row.id,
            status=session_row.status,
            chunk_size=session_row.chunk_size,
            total_chunks=session_row.total_chunks,
            received_bytes=session_row.received_bytes,
            expires_at=session_row.expires_at,
            missing_chunks=missing,
        )

    async def mark_finalized(self, session_row: UploadSession) -> None:
        """Record successful finalization before the row is dropped."""

        session_row.status = UploadSessionStatus.FINALIZED
        session_row.updated_at = utc_now()
        self._session.add(session_row)
        await self._session.commit()

    # -- chunk storage --

    async def get_chunk(
        self,
        session_id: UUID,
        chunk_index: int,
    ) -> UploadChunk:
        chunk = await self._session.get(UploadChunk, (session_id, chunk_index))
        if chunk is None:
            raise UploadChunkNotFoundError
        return chunk

    async def missing_chunks(self, session_id: UUID) -> list[int]:
        result = await self._session.exec(
            select(UploadChunk.chunk_index).where(
                UploadChunk.session_id == session_id,
                col(UploadChunk.received_at).is_(None),
            )
        )
        return sorted(int(index) for index in result.all())

    async def record_chunk(
        self,
        session_id: UUID,
        chunk_index: int,
        *,
        digest: str,
    ) -> ChunkPutResult:
        """Mark one chunk received and recompute received_bytes in one transaction."""

        chunk = await self.get_chunk(session_id, chunk_index)
        if chunk.received_at is None:
            chunk.received_at = utc_now()
            chunk.received_digest = digest
            self._session.add(chunk)

        result = await self._session.exec(
            select(func.coalesce(func.sum(UploadChunk.expected_size), 0)).where(
                UploadChunk.session_id == session_id,
                col(UploadChunk.received_at).is_not(None),
            )
        )
        received_bytes = int(result.one())

        session_row = await self._session.get(UploadSession, session_id)
        if session_row is None:
            raise RuntimeError("Chunk rows reference a missing session row")
        session_row.received_bytes = received_bytes
        session_row.updated_at = utc_now()
        self._session.add(session_row)
        await self._session.commit()

        missing = await self.missing_chunks(session_id)
        return ChunkPutResult(
            received_bytes=received_bytes,
            missing_chunks_count=len(missing),
        )

    # -- finalization --

    async def finalize(
        self,
        session_id: UUID,
        *,
        user_id: UUID,
    ) -> FinalizeResponse:
        """Assemble, copy, submit, and clean one chunked upload session."""

        session_row = await self.get_owned_session(session_id, user_id=user_id)
        self.assert_not_expired(session_row)
        if session_row.status == UploadSessionStatus.FINALIZED:
            raise UploadSessionFinalizedError

        missing = await self.missing_chunks(session_row.id)
        if missing:
            raise UploadSessionNotCompleteError(missing)
        not_stored = [
            index
            for index in range(session_row.total_chunks)
            if not paths.part_file(session_row.id, index).is_file()
        ]
        if not_stored:
            raise UploadSessionNotCompleteError(not_stored)

        assembled = await run_in_threadpool(
            self._assemble, session_row, session_row.total_chunks
        )

        settings = SplatGenerationWorkflowSettings.model_validate(session_row.settings)

        # Clean the DB only after a successful submission.
        try:
            result: FinalizeResponse = await self._submit(
                session_row,
                assembled,
                settings,
                user_id=user_id,
            )
        except Exception:
            await self._session.rollback()
            raise

        await self.mark_finalized(session_row)
        await self.delete_session(session_row)
        return result

    async def _submit(
        self,
        session_row: UploadSession,
        assembled: Path,
        settings: SplatGenerationWorkflowSettings,
        *,
        user_id: UUID,
    ) -> FinalizeResponse:
        buildings = BuildingService(self._session)
        reconstructions = ReconstructionService(self._session)

        try:
            if session_row.building_id is not None:
                building = await buildings.get(
                    session_row.building_id,
                    user_id=user_id,
                )
                if building is None:
                    raise UploadSessionNotFoundError
                reconstruction = await reconstructions.create_from_storage(
                    building=building,
                    video_path=assembled,
                    settings=settings,
                    video_format=session_row.file_extension,
                )
                return ReconstructionRead.model_validate(reconstruction)

            payload = BuildingCreate.model_validate(session_row.building_payload)
            created_building = await buildings.create(user_id=user_id, payload=payload)
            building_read = BuildingRead.model_validate(created_building)
            reconstruction = await reconstructions.create_from_storage(
                building=created_building,
                video_path=assembled,
                settings=settings,
                video_format=session_row.file_extension,
            )
            return BuildingFromReconstructionRead(
                building=building_read,
                reconstruction=ReconstructionRead.model_validate(reconstruction),
            )
        except ReconstructionCreationError as exc:
            raise UploadFinalizationError(
                str(exc),
                reconstruction_id=exc.reconstruction.id,
                building_id=exc.reconstruction.building_id,
            ) from exc

    @staticmethod
    def _assemble(session_row: UploadSession, total_chunks: int) -> Path:
        """Concatenate part files in chunk order into one staged video file."""

        directory = paths.session_dir(session_row.id)
        assembled = directory / f"assembled.{session_row.file_extension}"
        try:
            with assembled.open("wb") as destination:
                for index in range(total_chunks):
                    part = paths.part_file(session_row.id, index)
                    with part.open("rb") as source:
                        shutil.copyfileobj(source, destination)
        except OSError as exc:
            raise UploadAssemblyError("Failed to assemble uploaded chunks") from exc

        size = assembled.stat().st_size
        if size != session_row.total_size:
            assembled.unlink(missing_ok=True)
            raise UploadAssemblyError(
                f"Assembled size {size} does not match declared size "
                f"{session_row.total_size}"
            )
        return assembled

    # -- cleanup --

    async def delete_expired_sessions(self, *, now: datetime) -> int:
        """Delete sessions past their TTL together with their staging dirs."""

        result = await self._session.exec(
            select(UploadSession).where(UploadSession.expires_at < now)
        )
        rows = list(result.all())
        for row in rows:
            await self.delete_session(row)
        return len(rows)

    async def delete_finalized_sessions(self, *, older_than: datetime) -> int:
        """Delete sessions that finished finalization but were not removed."""

        result = await self._session.exec(
            select(UploadSession).where(
                UploadSession.status == UploadSessionStatus.FINALIZED,
                UploadSession.updated_at < older_than,
            )
        )
        rows = list(result.all())
        for row in rows:
            await self.delete_session(row)
        return len(rows)

    async def delete_orphan_temp_dirs(self) -> int:
        """Remove stale staging dirs that no active session claims."""

        root = paths.upload_root()
        if not root.is_dir():
            return 0
        stale_before = time() - ORPHAN_TEMP_GRACE_SECONDS
        removed = 0
        for entry in list(root.iterdir()):
            if not entry.is_dir():
                continue
            try:
                epoch = entry.stat().st_mtime
            except OSError:
                continue
            if epoch > stale_before:
                continue
            session_id = _uuid_from_hex(entry.name)
            if session_id is not None:
                row = await self._session.get(UploadSession, session_id)
                if row is not None and row.status == UploadSessionStatus.UPLOADING:
                    continue
            await run_in_threadpool(shutil.rmtree, entry, True)
            removed += 1
        return removed

    async def _commit_and_refresh(self, session_row: UploadSession) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(session_row)
