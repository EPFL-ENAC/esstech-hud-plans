from __future__ import annotations

import asyncio
import builtins
import logging
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.config import config
from api.lib.compute import scitas as scitas_compute
from api.lib.upload_storage import validate_completed_file
from api.lib.workflows import common as workflow_common
from api.models.building import Building
from api.models.reconstruction import (
    Reconstruction,
    ReconstructionArtifactUpdate,
    ReconstructionStatus,
)
from api.models.uploads import UploadStatus, UserUploads
from api.models.user import utc_now
from api.models.workflows import SplatGenerationWorkflowSettings

logger = logging.getLogger(__name__)

SortOrder = Literal["asc", "desc"]


class ReconstructionNotFoundError(Exception):
    pass


class ReconstructionInputNotFoundError(Exception):
    pass


class ReconstructionConflictError(Exception):
    pass


class ReconstructionCreationError(Exception):
    """Creation failed after a reconstruction row had been persisted."""

    def __init__(self, message: str, reconstruction: Reconstruction) -> None:
        super().__init__(message)
        self.reconstruction = reconstruction


class ReconstructionSchedulingError(ReconstructionCreationError):
    pass


class ReconstructionService:
    """Persist reconstructions and coordinate their Prefect workflow lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        reconstruction_id: UUID,
        *,
        building_id: UUID,
    ) -> Reconstruction | None:
        result = await self._session.exec(
            select(Reconstruction).where(
                Reconstruction.id == reconstruction_id,
                Reconstruction.building_id == building_id,
            )
        )
        return result.first()

    async def list(
        self,
        *,
        building_id: UUID,
        offset: int = 0,
        limit: int = 100,
        sort_order: SortOrder = "desc",
    ) -> builtins.list[Reconstruction]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if sort_order not in ("asc", "desc"):
            raise ValueError("sort_order must be asc or desc")

        ordering = (
            (col(Reconstruction.created_at).asc(), col(Reconstruction.id).asc())
            if sort_order == "asc"
            else (col(Reconstruction.created_at).desc(), col(Reconstruction.id).desc())
        )

        result = await self._session.exec(
            select(Reconstruction)
            .where(Reconstruction.building_id == building_id)
            .order_by(*ordering)
            .offset(offset)
            .limit(limit)
        )
        return list(result.all())

    async def create_from_upload(
        self,
        *,
        user_id: UUID,
        building_id: UUID,
        upload_id: UUID,
        settings: SplatGenerationWorkflowSettings,
    ) -> Reconstruction:
        """Persist a reconstruction, then schedule it if its upload is ready."""

        try:
            building = await self._session.scalar(
                select(Building)
                .where(Building.id == building_id, Building.user_id == user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if building is None:
                raise ReconstructionInputNotFoundError("Building not found")

            upload = await self._session.scalar(
                select(UserUploads)
                .where(UserUploads.id == upload_id, UserUploads.user_id == user_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if upload is None:
                raise ReconstructionInputNotFoundError("Upload not found")
            if upload.status not in {UploadStatus.PENDING, UploadStatus.UPLOADED}:
                raise ReconstructionConflictError("Upload has failed")
            if upload.status == UploadStatus.UPLOADED:
                validate_completed_file(Path(upload.file_path), upload.size_bytes)

            reconstruction = Reconstruction(
                building_id=building.id,
                upload_id=upload.id,
                status=ReconstructionStatus.WAITING_FOR_UPLOAD,  # _schedule_if_ready will update this if the upload is already complete
                settings=settings.model_dump(mode="json"),
            )
            self._session.add(reconstruction)
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

        # Publish the waiting row before rereading readiness. If completion's
        # scan missed this row, this read will observe the completed upload.
        return await self._schedule_if_ready(reconstruction.id)

    async def schedule_waiting_for_upload(self, upload_id: UUID) -> None:
        """Dispatch waiting rows independently after upload persistence succeeds."""

        result = await self._session.exec(
            select(Reconstruction.id)
            .where(
                Reconstruction.upload_id == upload_id,
                Reconstruction.status == ReconstructionStatus.WAITING_FOR_UPLOAD,
            )
            .order_by(col(Reconstruction.created_at), col(Reconstruction.id))
        )
        for reconstruction_id in result.all():
            try:
                await self._schedule_if_ready(reconstruction_id)
            except ReconstructionNotFoundError:
                # A waiting row may have been deleted after the scan.
                continue
            except ReconstructionSchedulingError:
                # The existing scheduling path records the failure on this row.
                # A failed reconstruction must not reject a completed upload.
                logger.exception(
                    "Failed to schedule reconstruction %s after upload %s",
                    reconstruction_id,
                    upload_id,
                )

    async def _schedule_if_ready(
        self,
        reconstruction_id: UUID,
    ) -> Reconstruction:
        scheduling_error: Exception | None = None
        try:
            reconstruction = await self._get_for_update(reconstruction_id)
            if reconstruction.status != ReconstructionStatus.WAITING_FOR_UPLOAD:
                await self._session.commit()
                return reconstruction

            upload = await self._session.scalar(
                select(UserUploads)
                .where(UserUploads.id == reconstruction.upload_id)
                .execution_options(populate_existing=True)
            )
            if upload is None or upload.status == UploadStatus.FAILED:
                reconstruction.status = ReconstructionStatus.FAILED
                reconstruction.error_message = "Source upload is unavailable"
            elif upload.status == UploadStatus.UPLOADED:
                reconstruction.status = ReconstructionStatus.PREPARING
                try:
                    workflow_id = await self._register_workflow(reconstruction, upload)
                except Exception as exc:
                    scheduling_error = exc
                    reconstruction.status = ReconstructionStatus.FAILED
                    reconstruction.error_message = f"{type(exc).__name__}: {exc}"
                else:
                    reconstruction.prefect_workflow_id = workflow_id
                    reconstruction.status = ReconstructionStatus.SCHEDULED
                    reconstruction.error_message = None
            else:
                await self._session.commit()
                return reconstruction

            reconstruction.updated_at = utc_now()
            self._session.add(reconstruction)
            await self._session.flush()
            await self._session.refresh(reconstruction)
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

        if scheduling_error is not None:
            raise ReconstructionSchedulingError(
                "Failed to prepare or schedule reconstruction workflow",
                reconstruction,
            ) from scheduling_error
        return reconstruction

    async def _register_workflow(
        self,
        reconstruction: Reconstruction,
        upload: UserUploads,
    ) -> UUID:
        """Prepare and register a run without releasing the caller's row lock."""

        from api.lib.workflows.splat_generation import (
            SplatGenerationArtifact,
            schedule_splat_generation_from_upload,
        )

        video_format = Path(upload.filename).suffix.removeprefix(".").lower() or "mp4"
        artifact = SplatGenerationArtifact(
            reconstruction.id,
            workflow_common.WORKFLOW_DATA_DIRECTORY,
            video_format,
        )
        reconstruction.workspace_directory = str(artifact.root_directory.resolve())
        reconstruction.input_video_path = str(artifact.video_path.resolve())
        async with asyncio.timeout(config.PREFECT_SUBMISSION_TIMEOUT_SECONDS):
            return await schedule_splat_generation_from_upload(
                artifact=artifact,
                upload_path=upload.file_path,
                upload_filename=upload.filename,
                settings=SplatGenerationWorkflowSettings.model_validate(
                    reconstruction.settings
                ),
                owner_id=upload.user_id,
                reconstruction_id=reconstruction.id,
            )

    async def cancel(self, reconstruction_id: UUID) -> Reconstruction:
        """Serialize cancellation with registration and worker lifecycle updates."""

        try:
            reconstruction = await self._get_for_update(reconstruction_id)
            if reconstruction.status == ReconstructionStatus.CANCELLED:
                await self._session.commit()
                return reconstruction
            if reconstruction.status not in {
                ReconstructionStatus.WAITING_FOR_UPLOAD,
                ReconstructionStatus.PREPARING,
                ReconstructionStatus.SCHEDULED,
                ReconstructionStatus.RUNNING,
            }:
                raise ReconstructionConflictError(
                    "Reconstruction is not processing "
                    f"(current status: {reconstruction.status})"
                )

            await self._cancel_external_work(reconstruction)
            reconstruction.mark_terminal_in_memory(
                ReconstructionStatus.CANCELLED,
                "Cancellation requested",
            )
            reconstruction.updated_at = utc_now()
            self._session.add(reconstruction)
            await self._session.flush()
            await self._session.refresh(reconstruction)
            await self._session.commit()
            return reconstruction
        except BaseException:
            await self._session.rollback()
            raise

    async def _cancel_external_work(self, reconstruction: Reconstruction) -> None:
        """Request external cancellation without changing the database transaction."""

        if (
            reconstruction.status
            in {
                ReconstructionStatus.PREPARING,
                ReconstructionStatus.SCHEDULED,
                ReconstructionStatus.RUNNING,
            }
            and reconstruction.prefect_workflow_id is not None
        ):
            try:
                await workflow_common.cancel_workflow(
                    reconstruction.prefect_workflow_id
                )
            except workflow_common.WorkflowNotFoundError:
                pass

        if config.USE_SCITAS:
            try:
                await run_in_threadpool(
                    scitas_compute.cancel_registered_jobs, reconstruction.id.hex
                )
            except Exception:
                logger.exception(
                    "Failed to cancel Slurm jobs for reconstruction %s",
                    reconstruction.id,
                )

    async def delete(self, reconstruction_id: UUID) -> None:
        """Cancel external work and delete under the same registration lock."""

        try:
            reconstruction = await self._get_for_update(reconstruction_id)
            await self._delete_locked(reconstruction)
            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise

    async def _delete_locked(self, reconstruction: Reconstruction) -> None:
        """Delete an already locked row; the caller owns the commit."""

        from api.lib.workflows.splat_generation import SplatGenerationArtifact

        await self._cancel_external_work(reconstruction)
        SplatGenerationArtifact.load(
            reconstruction.id,
            workflow_common.WORKFLOW_DATA_DIRECTORY,
        ).remove()
        await self._session.delete(reconstruction)

    async def mark_running(
        self,
        reconstruction_id: UUID,
        *,
        prefect_workflow_id: UUID,
    ) -> Reconstruction:
        try:
            reconstruction = await self._get_for_update(reconstruction_id)
            changed = reconstruction.mark_running_in_memory(prefect_workflow_id)
            if changed:
                reconstruction.updated_at = utc_now()
                self._session.add(reconstruction)
            await self._session.commit()
            return reconstruction
        except BaseException:
            await self._session.rollback()
            raise

    async def record_progress(
        self,
        reconstruction_id: UUID,
        *,
        progress: float,
        artifact_changes: ReconstructionArtifactUpdate | None = None,
    ) -> Reconstruction:
        try:
            reconstruction = await self._get_for_update(reconstruction_id)
            changed = reconstruction.record_progress_in_memory(
                progress,
                artifact_update=artifact_changes,
            )
            if changed:
                reconstruction.updated_at = utc_now()
                self._session.add(reconstruction)
            await self._session.commit()
            return reconstruction
        except BaseException:
            await self._session.rollback()
            raise

    async def mark_completed(
        self,
        reconstruction_id: UUID,
        *,
        artifacts: ReconstructionArtifactUpdate,
    ) -> Reconstruction:
        try:
            reconstruction = await self._get_for_update(reconstruction_id)
            changed = reconstruction.mark_completed_in_memory(artifacts)
            if changed:
                reconstruction.updated_at = utc_now()
                self._session.add(reconstruction)
            await self._session.commit()
            return reconstruction
        except BaseException:
            await self._session.rollback()
            raise

    async def mark_failed(
        self,
        reconstruction_id: UUID,
        *,
        error_message: str,
    ) -> Reconstruction:
        try:
            reconstruction = await self._get_for_update(reconstruction_id)
            changed = reconstruction.mark_terminal_in_memory(
                ReconstructionStatus.FAILED,
                error_message,
            )
            if changed:
                reconstruction.updated_at = utc_now()
                self._session.add(reconstruction)
            await self._session.commit()
            return reconstruction
        except BaseException:
            await self._session.rollback()
            raise

    async def mark_cancelled(
        self,
        reconstruction_id: UUID,
        *,
        error_message: str | None = None,
    ) -> Reconstruction:
        try:
            reconstruction = await self._get_for_update(reconstruction_id)
            changed = reconstruction.mark_terminal_in_memory(
                ReconstructionStatus.CANCELLED,
                error_message,
            )
            if changed:
                reconstruction.updated_at = utc_now()
                self._session.add(reconstruction)
            await self._session.commit()
            return reconstruction
        except BaseException:
            await self._session.rollback()
            raise

    async def mark_crashed(
        self,
        reconstruction_id: UUID,
        *,
        error_message: str | None = None,
    ) -> Reconstruction:
        try:
            reconstruction = await self._get_for_update(reconstruction_id)
            changed = reconstruction.mark_terminal_in_memory(
                ReconstructionStatus.CRASHED,
                error_message,
            )
            if changed:
                reconstruction.updated_at = utc_now()
                self._session.add(reconstruction)
            await self._session.commit()
            return reconstruction
        except BaseException:
            await self._session.rollback()
            raise

    async def _get_for_update(self, reconstruction_id: UUID) -> Reconstruction:
        result = await self._session.exec(
            select(Reconstruction)
            .where(Reconstruction.id == reconstruction_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        reconstruction = result.first()
        if reconstruction is None:
            raise ReconstructionNotFoundError
        return reconstruction
