import logging
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self
from uuid import UUID, uuid4

from api.config import config
from api.db import get_engine
from api.lib.compute import scitas as scitas_compute
from api.lib.compute.brush import run_brush_training
from api.lib.compute.colmap import run_colmap_reconstruction
from api.lib.compute.evaluate_video_frame import pick_frames
from api.lib.compute.ffmpeg import run_frame_extraction
from api.lib.utils.commands import (
    CommandExecutionEnvironment,
    LocalCommandExecutionEnvironment,
    ScitasCommandExecutionEnvironment,
)
from api.models.reconstruction import ReconstructionArtifactUpdate
from api.models.workflows import (
    BrushSettings,
    ColmapSettings,
    FramePickerSettings,
    SplatGenerationWorkflowSettings,
)
from api.services.reconstructions import (
    ReconstructionNotFoundError,
    ReconstructionService,
)
from fastapi import UploadFile
from prefect import flow, get_run_logger, task
from prefect.client.schemas.objects import FlowRun
from prefect.deployments import arun_deployment
from prefect.states import State
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

SPLAT_GENERATION_DEPLOYMENT = "splat-generation/default"
LOCAL_EXECUTION_ENVIRONMENT = LocalCommandExecutionEnvironment()
SCITAS_EXECUTION_ENVIRONMENT = ScitasCommandExecutionEnvironment()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _reconstruction_service() -> AsyncIterator[ReconstructionService]:
    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        yield ReconstructionService(session)


def _flow_run_reconstruction_id(flow_run: FlowRun) -> UUID | None:
    value = flow_run.parameters.get("reconstruction_id")
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _state_message(state: State) -> str | None:
    return state.message or state.name


def _completed_artifacts(flow_run: FlowRun) -> ReconstructionArtifactUpdate:
    parameters = flow_run.parameters
    settings = parameters.get("settings")
    uses_frame_picker = (
        isinstance(settings, dict) and settings.get("frame_picker") is not None
    )
    return ReconstructionArtifactUpdate(
        workspace_directory=str(parameters["workspace_directory"]),
        input_video_path=str(parameters["video_path"]),
        raw_frames_directory=(
            str(parameters["raw_frames_directory"]) if uses_frame_picker else None
        ),
        frames_directory=str(parameters["frames_directory"]),
        colmap_directory=str(parameters["colmap_directory"]),
        splat_path=str(parameters["splat_path"]),
    )


async def _reconstruction_running_hook(
    _flow: Any,
    flow_run: FlowRun,
    _state: State,
) -> None:
    reconstruction_id = _flow_run_reconstruction_id(flow_run)
    if reconstruction_id is None:
        return
    async with _reconstruction_service() as reconstructions:
        await reconstructions.mark_running(
            reconstruction_id,
            prefect_workflow_id=flow_run.id,
        )


async def _reconstruction_completed_hook(
    _flow: Any,
    flow_run: FlowRun,
    _state: State,
) -> None:
    reconstruction_id = _flow_run_reconstruction_id(flow_run)
    if reconstruction_id is None:
        return
    async with _reconstruction_service() as reconstructions:
        try:
            await reconstructions.mark_completed(
                reconstruction_id,
                artifacts=_completed_artifacts(flow_run),
            )
        except ReconstructionNotFoundError:
            # A delete request removes the row before the runner runs this
            # hook. There is no row to mark, so exit without an error.
            logger.info(
                "Reconstruction %s was deleted; skip completed update",
                reconstruction_id,
            )
            return


async def _reconstruction_failed_hook(
    _flow: Any,
    flow_run: FlowRun,
    state: State,
) -> None:
    reconstruction_id = _flow_run_reconstruction_id(flow_run)
    if reconstruction_id is None:
        return
    async with _reconstruction_service() as reconstructions:
        try:
            await reconstructions.mark_failed(
                reconstruction_id,
                error_message=_state_message(state) or "Reconstruction workflow failed",
            )
        except ReconstructionNotFoundError:
            # A delete request removes the row before the runner runs this
            # hook. There is no row to mark, so exit without an error.
            logger.info(
                "Reconstruction %s was deleted; skip failed update",
                reconstruction_id,
            )
            return


async def _reconstruction_cancelled_hook(
    _flow: Any,
    flow_run: FlowRun,
    state: State,
) -> None:
    reconstruction_id = _flow_run_reconstruction_id(flow_run)
    if reconstruction_id is None:
        return
    if config.USE_SCITAS:
        # Cancel the related Slurm jobs. Tasks blocked on I/O do not observe
        # the cancellation in the worker process, so it keeps their Slurm
        # jobs running.
        try:
            scitas_compute.cancel_registered_jobs(reconstruction_id.hex)
        except Exception:
            logger.exception(
                "Failed to cancel Slurm jobs for reconstruction %s", reconstruction_id
            )
    async with _reconstruction_service() as reconstructions:
        try:
            await reconstructions.mark_cancelled(
                reconstruction_id,
                error_message=_state_message(state),
            )
        except ReconstructionNotFoundError:
            # A delete request removes the row before the runner runs this
            # hook. There is no row to mark, so exit without an error.
            logger.info(
                "Reconstruction %s was deleted; skip cancelled update",
                reconstruction_id,
            )
            return


async def _reconstruction_crashed_hook(
    _flow: Any,
    flow_run: FlowRun,
    state: State,
) -> None:
    reconstruction_id = _flow_run_reconstruction_id(flow_run)
    if reconstruction_id is None:
        return
    async with _reconstruction_service() as reconstructions:
        try:
            await reconstructions.mark_crashed(
                reconstruction_id,
                error_message=_state_message(state),
            )
        except ReconstructionNotFoundError:
            # A delete request removes the row before the runner runs this
            # hook. There is no row to mark, so exit without an error.
            logger.info(
                "Reconstruction %s was deleted; skip crashed update",
                reconstruction_id,
            )
            return


async def _record_reconstruction_progress(
    reconstruction_id: UUID | None,
    *,
    progress: float,
    artifacts: ReconstructionArtifactUpdate | None = None,
) -> None:
    if reconstruction_id is None:
        return
    async with _reconstruction_service() as reconstructions:
        await reconstructions.record_progress(
            reconstruction_id,
            progress=progress,
            artifact_changes=artifacts,
        )


@dataclass(frozen=True)
class SplatGenerationArtifact:
    artifact_id: UUID
    storage_root: Path
    video_format: str = "mp4"

    @property
    def root_directory(self) -> Path:
        return self.storage_root / self.artifact_id.hex

    @property
    def video_path(self) -> Path:
        return (self.root_directory / "video" / "input").with_suffix(
            f".{self.video_format}"
        )

    @property
    def frames_directory(self) -> Path:
        return self.root_directory / "frames"

    @property
    def raw_frames_directory(self) -> Path:
        return self.root_directory / "frames_raw"

    @property
    def colmap_directory(self) -> Path:
        return self.root_directory / "colmap"

    @property
    def colmap_sparse_directory(self) -> Path:
        return self.colmap_directory / "sparse" / "0"

    @property
    def splat_path(self) -> Path:
        return self.root_directory / "splat.ply"

    @classmethod
    def create(
        cls,
        storage_root: Path,
        video_format: str = "mp4",
        *,
        artifact_id: UUID | None = None,
    ) -> Self:
        artifact = cls(artifact_id or uuid4(), storage_root, video_format)
        artifact.video_path.parent.mkdir(parents=True)
        return artifact

    @classmethod
    async def from_uploaded_file(
        cls,
        uploaded_file: UploadFile,
        storage_root: Path,
        *,
        artifact_id: UUID | None = None,
    ) -> Self:
        if not uploaded_file.filename:
            raise ValueError("Uploaded file must have a filename")

        file_extension = (
            Path(uploaded_file.filename).suffix.removeprefix(".").lower() or "mp4"
        )
        artifact = cls.create(
            storage_root,
            video_format=file_extension,
            artifact_id=artifact_id,
        )

        try:
            with artifact.video_path.open("wb") as destination:
                await run_in_threadpool(
                    shutil.copyfileobj, uploaded_file.file, destination
                )
        except Exception:
            artifact.remove()
            raise
        finally:
            await uploaded_file.close()

        return artifact

    @classmethod
    def load(cls, artifact_id: UUID, storage_root: Path) -> Self:
        return cls(artifact_id, storage_root)

    @classmethod
    def from_flow_run(cls, flow_run: FlowRun, storage_root: Path) -> Self:
        artifact_id_value = flow_run.parameters.get("artifact_id")
        if not isinstance(artifact_id_value, str):
            raise ValueError("Workflow does not contain an artifact ID")

        try:
            artifact_id = UUID(artifact_id_value)
        except ValueError as exc:
            raise ValueError("Workflow contains an invalid artifact ID") from exc

        return cls.load(artifact_id, storage_root)

    def remove(self) -> None:
        shutil.rmtree(self.root_directory, ignore_errors=True)


@task(name="extract-video-frames")
def extract_frames_task(
    workspace_directory: str,
    video_path: str,
    frames_directory: str,
    fps: float | None,
    fit_in_width: int,
    fit_in_height: int,
    execution_environment: CommandExecutionEnvironment = LOCAL_EXECUTION_ENVIRONMENT,
) -> str:
    run_logger = get_run_logger()

    def log_ffmpeg(record: str) -> None:
        run_logger.info("ffmpeg: %s", record)

    output_directory = run_frame_extraction(
        Path(video_path),
        Path(frames_directory),
        workspace_directory=Path(workspace_directory),
        execution_environment=execution_environment,
        fps=fps,
        fit_in_width=fit_in_width,
        fit_in_height=fit_in_height,
        on_log=log_ffmpeg,
    )
    return str(output_directory)


@task(name="pick-video-frames")
def pick_frames_task(
    workspace_directory: str,
    video_path: str,
    input_frames_directory: str,
    frames_directory: str,
    settings: FramePickerSettings,
) -> str:
    run_logger = get_run_logger()

    def log_frame_picker(msg: str, progress: float | None = None) -> None:
        if progress is None:
            run_logger.info("frame-picker: %s", msg)
        else:
            run_logger.info("frame-picker [%d%%]: %s", round(progress * 100), msg)

    selected_frames = pick_frames(
        video_source_path=video_path,
        input_folder=input_frames_directory,
        output_folder=frames_directory,
        distance_threshold=settings.distance_threshold,
        min_fps=settings.min_fps,
        remove_outliers=settings.remove_outliers,
        outlier_window_size=7,
        outlier_sharpness_ratio=settings.outlier_sharpness_ratio,
        on_progress=log_frame_picker,
        output_symlink_relative_to=workspace_directory,
    )
    if not selected_frames:
        raise RuntimeError("Frame picker completed without selecting any frames")

    return str(Path(frames_directory).resolve())


@task(name="reconstruct-with-colmap")
def reconstruct_with_colmap_task(
    workspace_directory: str,
    frames_directory: str,
    colmap_directory: str,
    settings: ColmapSettings,
    execution_environment: CommandExecutionEnvironment = LOCAL_EXECUTION_ENVIRONMENT,
) -> str:
    run_logger = get_run_logger()

    def log_colmap(record: str) -> None:
        run_logger.info("colmap: %s", record)

    output_directory = run_colmap_reconstruction(
        Path(frames_directory),
        Path(colmap_directory),
        settings,
        workspace_directory=Path(workspace_directory),
        execution_environment=execution_environment,
        on_log=log_colmap,
    )
    return str(output_directory)


@task(name="train-with-brush")
def train_with_brush_task(
    workspace_directory: str,
    dataset_directory: str,
    splat_path: str,
    settings: BrushSettings,
    execution_environment: CommandExecutionEnvironment = LOCAL_EXECUTION_ENVIRONMENT,
) -> str:
    run_logger = get_run_logger()

    def log_brush(record: str) -> None:
        run_logger.info("brush: %s", record)

    output_path = run_brush_training(
        Path(dataset_directory),
        Path(splat_path),
        settings,
        workspace_directory=Path(workspace_directory),
        execution_environment=execution_environment,
        on_log=log_brush,
    )
    return str(output_path)


@flow(
    name="splat-generation",
    on_running=[_reconstruction_running_hook],
    on_completion=[_reconstruction_completed_hook],
    on_failure=[_reconstruction_failed_hook],
    on_cancellation=[_reconstruction_cancelled_hook],
    on_crashed=[_reconstruction_crashed_hook],
)
async def splat_generation_flow(
    artifact_id: UUID,
    workspace_directory: str,
    video_path: str,
    raw_frames_directory: str,
    frames_directory: str,
    colmap_directory: str,
    splat_path: str,
    settings: SplatGenerationWorkflowSettings,
    owner_id: UUID,
    reconstruction_id: UUID | None = None,
) -> str:
    run_logger = get_run_logger()
    run_logger.info("Starting splat generation for artifact %s", artifact_id)

    gpu_execution_environment = (
        SCITAS_EXECUTION_ENVIRONMENT
        if config.USE_SCITAS
        else LOCAL_EXECUTION_ENVIRONMENT
    )

    frame_picker_settings = settings.frame_picker
    extraction_directory = (
        raw_frames_directory if frame_picker_settings is not None else frames_directory
    )
    extracted_frames_directory = extract_frames_task(
        workspace_directory=workspace_directory,
        video_path=video_path,
        frames_directory=extraction_directory,
        fps=None if frame_picker_settings is not None else settings.ffmpeg.fps,
        fit_in_width=settings.ffmpeg.fit_in_width,
        fit_in_height=settings.ffmpeg.fit_in_height,
        execution_environment=LOCAL_EXECUTION_ENVIRONMENT,
    )
    await _record_reconstruction_progress(
        reconstruction_id,
        progress=0.25,
        artifacts=ReconstructionArtifactUpdate(
            **(
                {"raw_frames_directory": extracted_frames_directory}
                if frame_picker_settings is not None
                else {"frames_directory": extracted_frames_directory}
            )
        ),
    )
    selected_frames_directory = (
        pick_frames_task(
            workspace_directory=workspace_directory,
            video_path=video_path,
            input_frames_directory=extracted_frames_directory,
            frames_directory=frames_directory,
            settings=frame_picker_settings,
        )
        if frame_picker_settings is not None
        else extracted_frames_directory
    )
    await _record_reconstruction_progress(
        reconstruction_id,
        progress=0.40,
        artifacts=ReconstructionArtifactUpdate(
            frames_directory=selected_frames_directory,
        ),
    )
    reconstructed_colmap_directory = reconstruct_with_colmap_task(
        workspace_directory=workspace_directory,
        frames_directory=selected_frames_directory,
        colmap_directory=colmap_directory,
        settings=settings.colmap,
        execution_environment=gpu_execution_environment,
    )
    await _record_reconstruction_progress(
        reconstruction_id,
        progress=0.70,
        artifacts=ReconstructionArtifactUpdate(
            colmap_directory=reconstructed_colmap_directory,
        ),
    )
    generated_splat_path = train_with_brush_task(
        workspace_directory=workspace_directory,
        dataset_directory=str(Path(reconstructed_colmap_directory).parent),
        splat_path=splat_path,
        settings=settings.brush,
        execution_environment=gpu_execution_environment,
    )
    await _record_reconstruction_progress(
        reconstruction_id,
        progress=0.95,
        artifacts=ReconstructionArtifactUpdate(splat_path=generated_splat_path),
    )
    return generated_splat_path


async def schedule_splat_generation(
    artifact: SplatGenerationArtifact,
    settings: SplatGenerationWorkflowSettings,
    owner_id: UUID,
    reconstruction_id: UUID | None = None,
) -> UUID:
    parameters: dict[str, object] = {
        "artifact_id": str(artifact.artifact_id),
        "workspace_directory": str(artifact.root_directory.resolve()),
        "video_path": str(artifact.video_path.resolve()),
        "raw_frames_directory": str(artifact.raw_frames_directory.resolve()),
        "frames_directory": str(artifact.frames_directory.resolve()),
        "colmap_directory": str(artifact.colmap_directory.resolve()),
        "splat_path": str(artifact.splat_path.resolve()),
        "settings": settings.model_dump(mode="json"),
        "owner_id": str(owner_id),
    }
    extra_options: dict[str, object] = {}
    if reconstruction_id is not None:
        parameters["reconstruction_id"] = str(reconstruction_id)
        extra_options["idempotency_key"] = f"reconstruction:{reconstruction_id}"

    flow_run = await arun_deployment(
        name=SPLAT_GENERATION_DEPLOYMENT,
        parameters=parameters,
        timeout=0,
        as_subflow=False,
        **extra_options,
    )
    return flow_run.id
