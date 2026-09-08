from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from api.lib.workflows import common as workflow_common
from api.models.building import Building
from api.models.reconstruction import (
    Reconstruction,
    ReconstructionArtifactUpdate,
    ReconstructionStatus,
)
from api.models.user import utc_now
from api.models.workflows import SplatGenerationWorkflowSettings
from fastapi import UploadFile
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

SortOrder = Literal["asc", "desc"]


class ReconstructionNotFoundError(Exception):
    pass


class ReconstructionCreationError(Exception):
    """Creation failed after a reconstruction row had been persisted."""

    def __init__(self, message: str, reconstruction: Reconstruction) -> None:
        super().__init__(message)
        self.reconstruction = reconstruction


class ReconstructionVideoStorageError(ReconstructionCreationError):
    pass


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
    ) -> list[Reconstruction]:
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

    async def create_from_video(
        self,
        *,
        building: Building,
        video: UploadFile,
        settings: SplatGenerationWorkflowSettings,
    ) -> Reconstruction:
        """Persist an uploaded video and schedule its reconstruction workflow."""

        reconstruction = Reconstruction(
            building_id=building.id,
            settings=settings.model_dump(mode="json"),
        )
        self._session.add(reconstruction)
        await self._commit_and_refresh(reconstruction)

        # Imports stay local so the Prefect flow can call this service to publish
        # lifecycle updates without creating a module import cycle.
        from api.lib.workflows.splat_generation import (
            SplatGenerationArtifact,
            schedule_splat_generation,
        )

        try:
            artifact = await SplatGenerationArtifact.from_uploaded_file(
                video,
                workflow_common.WORKFLOW_DATA_DIRECTORY,
                artifact_id=reconstruction.id,
            )
        except Exception as exc:
            SplatGenerationArtifact.load(
                reconstruction.id,
                workflow_common.WORKFLOW_DATA_DIRECTORY,
            ).remove()
            failed = await self._mark_failed_best_effort(reconstruction.id, exc)
            raise ReconstructionVideoStorageError(
                "Failed to store reconstruction video",
                failed,
            ) from exc

        reconstruction = await self.record_progress(
            reconstruction.id,
            progress=0.0,
            artifact_changes=ReconstructionArtifactUpdate(
                workspace_directory=str(artifact.root_directory.resolve()),
                input_video_path=str(artifact.video_path.resolve()),
            ),
        )

        try:
            workflow_id = await schedule_splat_generation(
                artifact=artifact,
                settings=settings,
                owner_id=building.user_id,
                reconstruction_id=reconstruction.id,
            )
        except Exception as exc:
            failed = await self._mark_failed_best_effort(
                reconstruction.id,
                exc,
                only_if_preparing=True,
            )
            raise ReconstructionSchedulingError(
                "Failed to schedule reconstruction workflow",
                failed,
            ) from exc

        return await self._record_scheduled_workflow(reconstruction, workflow_id)

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
        reconstruction = await self._session.get(Reconstruction, reconstruction_id)
        if reconstruction is None:
            raise ReconstructionNotFoundError
        await self._session.refresh(reconstruction)
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
