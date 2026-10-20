from __future__ import annotations

import builtins
import logging
from pathlib import Path
from typing import Literal
from uuid import UUID

from sqlalchemy import update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.config import config
from api.lib.compute import scitas as scitas_compute
from api.lib.workflows import common as workflow_common
from api.lib.workflows import tus_cleanup
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


async def _remove_tus_staging_upload(workflow_id: UUID) -> None:
    try:
        parameters = await workflow_common.read_flow_run_parameters(workflow_id)
    except Exception:
        logger.exception(
            "Failed to read flow run %s for tus staging cleanup", workflow_id
        )
        return
    if parameters is None:
        return
    tus_upload_path = parameters.get("tus_upload_path")
    if not isinstance(tus_upload_path, str):
        return
    try:
        tus_cleanup.remove_staging_upload(tus_upload_path)
    except OSError:
        logger.exception("Failed to remove tus staging upload %s", tus_upload_path)


class ReconstructionNotFoundError(Exception):
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
        building: Building,
        upload: UserUploads,
        settings: SplatGenerationWorkflowSettings,
    ) -> Reconstruction:
        """Persist a reconstruction, then schedule it if its upload is ready."""

        reconstruction = Reconstruction(
            building_id=building.id,
            upload_id=upload.id,
            status=ReconstructionStatus.WAITING_FOR_UPLOAD,
            settings=settings.model_dump(mode="json"),
        )
        self._session.add(reconstruction)
        await self._commit_and_refresh(reconstruction)

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

    async def cancel_waiting(self, reconstruction_id: UUID) -> Reconstruction:
        """Cancel only while waiting; otherwise return the freshly read row."""

        await self._transition_waiting(
            reconstruction_id,
            ReconstructionStatus.CANCELLED,
            error_message="Cancellation requested",
        )
        return await self._get_or_raise(reconstruction_id)

    async def _transition_waiting(
        self,
        reconstruction_id: UUID,
        status: ReconstructionStatus,
        *,
        error_message: str | None = None,
    ) -> bool:
        """Commit an atomic claim shared by scheduling and cancellation."""

        try:
            result = await self._session.exec(
                update(Reconstruction)
                .where(
                    col(Reconstruction.id) == reconstruction_id,
                    col(Reconstruction.status)
                    == ReconstructionStatus.WAITING_FOR_UPLOAD,
                )
                .values(
                    status=status,
                    error_message=error_message,
                    updated_at=utc_now(),
                )
                .returning(col(Reconstruction.id))
                .execution_options(synchronize_session=False)
            )
            changed = result.scalar_one_or_none() is not None
            await self._session.commit()
            return changed
        except Exception:
            await self._session.rollback()
            raise

    async def _schedule_if_ready(
        self,
        reconstruction_id: UUID,
    ) -> Reconstruction:
        reconstruction = await self._get_or_raise(reconstruction_id)
        if reconstruction.status != ReconstructionStatus.WAITING_FOR_UPLOAD:
            return reconstruction

        result = await self._session.exec(
            select(UserUploads)
            .where(UserUploads.id == reconstruction.upload_id)
            .execution_options(populate_existing=True)
        )
        upload = result.first()
        if upload is None or upload.status != UploadStatus.UPLOADED:
            return reconstruction

        if not await self._transition_waiting(
            reconstruction.id,
            ReconstructionStatus.PREPARING,
        ):
            return await self._get_or_raise(reconstruction.id)

        # Imports stay local so the Prefect flow can call this service to publish
        # lifecycle updates without creating a module import cycle.
        from api.lib.workflows.splat_generation import (
            SplatGenerationArtifact,
            schedule_splat_generation_from_tus,
        )

        video_format = Path(upload.filename).suffix.removeprefix(".").lower() or "mp4"
        artifact = SplatGenerationArtifact(
            reconstruction.id,
            workflow_common.WORKFLOW_DATA_DIRECTORY,
            video_format,
        )

        try:
            reconstruction = await self.record_progress(
                reconstruction.id,
                progress=0.0,
                artifact_changes=ReconstructionArtifactUpdate(
                    workspace_directory=str(artifact.root_directory.resolve()),
                    input_video_path=str(artifact.video_path.resolve()),
                ),
            )

            workflow_id = await schedule_splat_generation_from_tus(
                artifact=artifact,
                tus_upload_path=upload.file_path,
                tus_video_filename=upload.filename,
                settings=SplatGenerationWorkflowSettings.model_validate(
                    reconstruction.settings
                ),
                owner_id=upload.user_id,
                reconstruction_id=reconstruction.id,
            )
        except Exception as exc:
            failed = await self._mark_failed_best_effort(
                reconstruction_id,
                exc,
                only_if_preparing=True,
            )
            raise ReconstructionSchedulingError(
                "Failed to prepare or schedule reconstruction workflow",
                failed,
            ) from exc

        return await self._record_scheduled_workflow(reconstruction, workflow_id)

    async def delete(self, reconstruction: Reconstruction) -> None:
        """Cancel a pending workflow, remove stored artifacts, and drop the row."""

        # Imports stay local so the Prefect flow can call this service to publish
        # lifecycle updates without creating a module import cycle.
        from api.lib.workflows.splat_generation import SplatGenerationArtifact

        if (
            reconstruction.status
            in (
                ReconstructionStatus.PREPARING,
                ReconstructionStatus.SCHEDULED,
                ReconstructionStatus.RUNNING,
            )
            and reconstruction.prefect_workflow_id is not None
        ):
            try:
                await workflow_common.cancel_workflow(
                    reconstruction.prefect_workflow_id
                )
            except workflow_common.WorkflowNotFoundError:
                # The workflow run no longer exists.
                pass

        if config.USE_SCITAS:
            try:
                # Run the cancellation in a threadpool. The call does blocking
                # I/O (SSH and Prefect API calls), so it must not block the
                # event loop of the async request handler.
                await run_in_threadpool(
                    scitas_compute.cancel_registered_jobs, reconstruction.id.hex
                )
            except Exception:
                logger.exception(
                    "Failed to cancel Slurm jobs for reconstruction %s",
                    reconstruction.id,
                )

        SplatGenerationArtifact.load(
            reconstruction.id,
            workflow_common.WORKFLOW_DATA_DIRECTORY,
        ).remove()

        if reconstruction.prefect_workflow_id is not None:
            await _remove_tus_staging_upload(reconstruction.prefect_workflow_id)

        try:
            await self._session.delete(reconstruction)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

    async def mark_running(
        self,
        reconstruction_id: UUID,
        *,
        prefect_workflow_id: UUID,
    ) -> Reconstruction:
        reconstruction = await self._get_or_raise(reconstruction_id)
        if not reconstruction.mark_running_in_memory(prefect_workflow_id):
            return reconstruction
        return await self._save(reconstruction)

    async def record_progress(
        self,
        reconstruction_id: UUID,
        *,
        progress: float,
        artifact_changes: ReconstructionArtifactUpdate | None = None,
    ) -> Reconstruction:
        reconstruction = await self._get_or_raise(reconstruction_id)
        changed = reconstruction.record_progress_in_memory(
            progress,
            artifact_update=artifact_changes,
        )

        return await self._save(reconstruction) if changed else reconstruction

    async def mark_completed(
        self,
        reconstruction_id: UUID,
        *,
        artifacts: ReconstructionArtifactUpdate,
    ) -> Reconstruction:
        reconstruction = await self._get_or_raise(reconstruction_id)
        reconstruction.mark_completed_in_memory(artifacts)
        return await self._save(reconstruction)

    async def mark_failed(
        self,
        reconstruction_id: UUID,
        *,
        error_message: str,
    ) -> Reconstruction:
        reconstruction = await self._get_or_raise(reconstruction_id)
        if not reconstruction.mark_terminal_in_memory(
            ReconstructionStatus.FAILED,
            error_message,
        ):
            return reconstruction
        return await self._save(reconstruction)

    async def mark_cancelled(
        self,
        reconstruction_id: UUID,
        *,
        error_message: str | None = None,
    ) -> Reconstruction:
        reconstruction = await self._get_or_raise(reconstruction_id)
        if not reconstruction.mark_terminal_in_memory(
            ReconstructionStatus.CANCELLED,
            error_message,
        ):
            return reconstruction
        return await self._save(reconstruction)

    async def mark_crashed(
        self,
        reconstruction_id: UUID,
        *,
        error_message: str | None = None,
    ) -> Reconstruction:
        reconstruction = await self._get_or_raise(reconstruction_id)
        if not reconstruction.mark_terminal_in_memory(
            ReconstructionStatus.CRASHED,
            error_message,
        ):
            return reconstruction
        return await self._save(reconstruction)

    async def _record_scheduled_workflow(
        self,
        reconstruction: Reconstruction,
        workflow_id: UUID,
    ) -> Reconstruction:
        # A worker can start before arun_deployment returns. Refresh first and
        # never move a row that is already running or terminal back to scheduled.
        await self._session.refresh(reconstruction)
        reconstruction.mark_scheduled_in_memory(workflow_id)
        return await self._save(reconstruction)

    async def _mark_failed_best_effort(
        self,
        reconstruction_id: UUID,
        exc: Exception,
        *,
        only_if_preparing: bool = False,
    ) -> Reconstruction:
        message = f"{type(exc).__name__}: {exc}"
        try:
            reconstruction = await self._get_or_raise(reconstruction_id)
            if (
                only_if_preparing
                and reconstruction.status != ReconstructionStatus.PREPARING
            ):
                return reconstruction
            return await self.mark_failed(
                reconstruction_id,
                error_message=message,
            )
        except Exception:
            logger.exception(
                "Failed to mark reconstruction %s as failed",
                reconstruction_id,
            )
            fallback = await self._session.get(Reconstruction, reconstruction_id)
            if fallback is None:
                raise ReconstructionNotFoundError from exc
            return fallback

    async def _get_or_raise(self, reconstruction_id: UUID) -> Reconstruction:
        result = await self._session.exec(
            select(Reconstruction)
            .where(Reconstruction.id == reconstruction_id)
            .execution_options(populate_existing=True)
        )
        reconstruction = result.first()
        if reconstruction is None:
            raise ReconstructionNotFoundError
        return reconstruction

    async def _save(self, reconstruction: Reconstruction) -> Reconstruction:
        reconstruction.updated_at = utc_now()
        self._session.add(reconstruction)
        await self._commit_and_refresh(reconstruction)
        return reconstruction

    async def _commit_and_refresh(self, reconstruction: Reconstruction) -> None:
        try:
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        await self._session.refresh(reconstruction)
