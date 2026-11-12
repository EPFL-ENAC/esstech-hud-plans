import logging
import math
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Literal, Self
from uuid import UUID, uuid4

from anyio import from_thread
from prefect import flow, get_run_logger, task
from prefect.cache_policies import DEFAULT
from prefect.client.schemas.objects import FlowRun
from prefect.deployments import arun_deployment
from prefect.states import State
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.config import config
from api.db import get_engine
from api.lib.compute import scitas as scitas_compute
from api.lib.compute.evaluate_video_frame import pick_frames
from api.lib.compute.ffmpeg import run_frame_extraction
from api.lib.compute.point_cloud import generate_plan_point_cloud
from api.lib.compute.progress import (
    FfmpegProgressEstimator,
    ReportProgress,
    SpirulaMaskProgressEstimator,
    SpirulaSfmProgressEstimator,
    SpirulaTrainProgressEstimator,
)
from api.lib.compute.spirula import (
    maskable_frames,
    run_spirula_geometry,
    run_spirula_masks,
    run_spirula_sfm,
    run_spirula_train,
)
from api.lib.utils.commands import (
    CommandExecutionEnvironment,
    LocalCommandExecutionEnvironment,
    ScitasCommandExecutionEnvironment,
)
from api.lib.workflows import common as workflow_common
from api.models.reconstruction import Reconstruction, ReconstructionArtifactUpdate
from api.models.workflows import (
    FramePickerSettings,
    ObjectMaskSettings,
    SpirulaGeometrySettings,
    SpirulaSfmSettings,
    SpirulaTrainSettings,
    SplatGenerationWorkflowSettings,
)
from api.services.reconstructions import (
    ReconstructionNotFoundError,
    ReconstructionService,
)

SPLAT_GENERATION_DEPLOYMENT = "splat-generation/default"
SCITAS_EXECUTION_ENVIRONMENT = ScitasCommandExecutionEnvironment()

logger = logging.getLogger(__name__)

ProgressWriteOutcome = Literal["recorded", "failed", "disabled"]


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
            logger.info(
                "Reconstruction %s was deleted; skip failed update",
                reconstruction_id,
            )
            return


async def _reconstruction_cancelled_hook(
    flow: Any,
    flow_run: FlowRun,
    state: State,
) -> None:
    reconstruction_id = _flow_run_reconstruction_id(flow_run)
    if reconstruction_id is None:
        return
    if config.USE_SCITAS:
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
            logger.info(
                "Reconstruction %s was deleted; skip cancelled update",
                reconstruction_id,
            )
            return


async def _reconstruction_crashed_hook(
    flow: Any,
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
) -> ProgressWriteOutcome:
    """Publish optional progress without letting reporting failures stop compute."""
    if reconstruction_id is None:
        return "disabled"
    try:
        async with _reconstruction_service() as reconstructions:
            await reconstructions.record_progress(
                reconstruction_id,
                progress=progress,
                artifact_changes=artifacts,
            )
    except ReconstructionNotFoundError:
        logger.info(
            "Reconstruction %s was deleted; skip progress update",
            reconstruction_id,
        )
        return "disabled"
    except Exception:
        logger.warning(
            "Could not publish progress %s for reconstruction %s",
            progress,
            reconstruction_id,
            exc_info=True,
        )
        return "failed"
    return "recorded"


def _progress_callback(
    reconstruction_id: UUID | None,
    start: float,
    end: float,
    throttle_seconds: float = 2.0,
) -> ReportProgress | None:
    """Scale and throttle updates from a task running in an AnyIO worker thread."""
    if reconstruction_id is None:
        return None

    last_progress = start
    last_attempt = -math.inf
    enabled = True

    def report_progress(fraction: float) -> None:
        nonlocal last_progress, last_attempt, enabled
        if not enabled or not math.isfinite(fraction):
            return

        # Reserve the endpoint for successful execution and artifact validation.
        progress = start + (end - start) * min(max(fraction, 0.0), 0.99)
        now = time.monotonic()
        if progress <= last_progress or now - last_attempt < throttle_seconds:
            return

        last_attempt = now
        try:
            outcome = from_thread.run(
                partial(
                    _record_reconstruction_progress,
                    reconstruction_id,
                    progress=progress,
                )
            )
        except Exception:
            logger.warning(
                "Could not publish progress for reconstruction %s",
                reconstruction_id,
                exc_info=True,
            )
        else:
            if outcome == "disabled":
                enabled = False
            elif outcome == "recorded":
                last_progress = progress

    return report_progress


@dataclass(frozen=True)
class SplatGenerationArtifact:
    artifact_id: UUID
    storage_root: Path

    @property
    def root_directory(self) -> Path:
        return self.storage_root / self.artifact_id.hex

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
        *,
        artifact_id: UUID | None = None,
    ) -> Self:
        artifact = cls(artifact_id or uuid4(), storage_root)
        artifact.root_directory.mkdir(parents=True)
        return artifact

    @classmethod
    def load(cls, artifact_id: UUID, storage_root: Path) -> Self:
        return cls(artifact_id, storage_root)

    @classmethod
    def from_local_reconstruction(cls, reconstruction: Reconstruction) -> Self:
        """Locate reconstruction artifacts under this process's storage root."""
        return cls.load(
            reconstruction.id,
            workflow_common.WORKFLOW_DATA_DIRECTORY.resolve(),
        )

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


# Reporting and process ownership are execution details, not cached inputs.
@task(
    name="extract-video-frames",
    cache_policy=DEFAULT - "report_progress" - "execution_environment",
)
async def extract_frames_task(
    workspace_directory: str,
    video_path: str,
    frames_directory: str,
    fps: float | None,
    fit_in_width: int,
    fit_in_height: int,
    execution_environment: CommandExecutionEnvironment,
    report_progress: ReportProgress | None = None,
) -> str:
    run_logger = get_run_logger()
    estimator = FfmpegProgressEstimator()

    def log_ffmpeg(record: str) -> None:
        run_logger.info("ffmpeg: %s", record)
        progress = estimator.feed(record)
        if progress is not None and report_progress is not None:
            report_progress(progress)

    output_directory = await execution_environment.run(
        partial(
            run_frame_extraction,
            Path(video_path),
            Path(frames_directory),
            workspace_directory=Path(workspace_directory),
            execution_environment=execution_environment,
            fps=fps,
            fit_in_width=fit_in_width,
            fit_in_height=fit_in_height,
            on_log=log_ffmpeg,
        ),
    )
    return str(output_directory)


@task(name="pick-video-frames", cache_policy=DEFAULT - "report_progress")
async def pick_frames_task(
    workspace_directory: str,
    video_path: str,
    input_frames_directory: str,
    frames_directory: str,
    settings: FramePickerSettings,
    report_progress: ReportProgress | None = None,
) -> str:
    run_logger = get_run_logger()

    def log_frame_picker(msg: str, progress: float | None = None) -> None:
        if progress is None:
            run_logger.info("frame-picker: %s", msg)
        else:
            run_logger.info("frame-picker [%d%%]: %s", round(progress * 100), msg)
            if report_progress is not None:
                report_progress(progress)

    selected_frames = await run_in_threadpool(
        pick_frames,
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


@task(
    name="generate-masks",
    cache_policy=DEFAULT - "report_progress" - "execution_environment",
)
async def generate_masks_task(
    workspace_directory: str,
    frames_directory: str,
    remove_objects: ObjectMaskSettings,
    keep_objects: ObjectMaskSettings,
    execution_environment: CommandExecutionEnvironment,
    report_progress: ReportProgress | None = None,
) -> None:
    pass_count = int(remove_objects.enabled) + int(keep_objects.enabled)
    if pass_count == 0:
        return

    run_logger = get_run_logger()
    frames = maskable_frames(Path(frames_directory))
    if not frames:
        raise RuntimeError(
            f"Frames directory contains no maskable images: {frames_directory}"
        )
    estimator = SpirulaMaskProgressEstimator(
        total_frames=len(frames),
        pass_count=pass_count,
    )

    def log_spirula_masks(record: str) -> None:
        run_logger.info("spirula-masks: %s", record)
        progress = estimator.feed(record)
        if progress is not None and report_progress is not None:
            report_progress(progress)

    await execution_environment.run(
        partial(
            run_spirula_masks,
            Path(frames_directory),
            Path(workspace_directory),
            remove_objects,
            keep_objects,
            execution_environment=execution_environment,
            on_log=log_spirula_masks,
        ),
    )


@task(
    name="reconstruct-with-spirula-sfm",
    cache_policy=DEFAULT - "report_progress" - "execution_environment",
)
async def reconstruct_with_spirula_task(
    workspace_directory: str,
    frames_directory: str,
    colmap_directory: str,
    settings: SpirulaSfmSettings,
    execution_environment: CommandExecutionEnvironment,
    report_progress: ReportProgress | None = None,
) -> str:
    run_logger = get_run_logger()
    estimator = SpirulaSfmProgressEstimator()

    def log_spirula_sfm(record: str) -> None:
        run_logger.info("spirula-sfm: %s", record)
        progress = estimator.feed(record)
        if progress is not None and report_progress is not None:
            report_progress(progress)

    output_directory = await execution_environment.run(
        partial(
            run_spirula_sfm,
            Path(frames_directory),
            Path(colmap_directory),
            settings,
            workspace_directory=Path(workspace_directory),
            execution_environment=execution_environment,
            on_log=log_spirula_sfm,
        ),
    )
    return str(output_directory)


@task(
    name="predict-geometry-maps",
    cache_policy=DEFAULT - "report_progress" - "execution_environment",
)
async def predict_geometry_maps_task(
    workspace_directory: str,
    dataset_directory: str,
    settings: SpirulaGeometrySettings,
    execution_environment: CommandExecutionEnvironment,
    report_progress: ReportProgress | None = None,
) -> str:
    run_logger = get_run_logger()

    def log_spirula_geometry(record: str) -> None:
        run_logger.info("spirula-geometry: %s", record)

    output_directory = await execution_environment.run(
        partial(
            run_spirula_geometry,
            Path(dataset_directory),
            settings,
            workspace_directory=Path(workspace_directory),
            execution_environment=execution_environment,
            on_log=log_spirula_geometry,
        ),
    )
    run_logger.info("Predicted geometry maps for %s", output_directory)
    return str(output_directory)


@task(
    name="train-with-spirula",
    cache_policy=DEFAULT - "report_progress" - "execution_environment",
)
async def train_with_spirula_task(
    workspace_directory: str,
    dataset_directory: str,
    splat_path: str,
    settings: SpirulaTrainSettings,
    execution_environment: CommandExecutionEnvironment,
    report_progress: ReportProgress | None = None,
) -> str:
    run_logger = get_run_logger()
    estimator = SpirulaTrainProgressEstimator()

    def log_spirula_train(record: str) -> None:
        run_logger.info("spirula-train: %s", record)
        progress = estimator.feed(record)
        if progress is not None and report_progress is not None:
            report_progress(progress)

    output_path = await execution_environment.run(
        partial(
            run_spirula_train,
            Path(dataset_directory),
            Path(splat_path),
            settings,
            workspace_directory=Path(workspace_directory),
            execution_environment=execution_environment,
            on_log=log_spirula_train,
        ),
    )
    return str(output_path)


@task(name="generate-plan-point-cloud", cache_policy=DEFAULT - "report_progress")
async def generate_plan_point_cloud_task(
    splat_path: str,
    colmap_directory: str,
) -> None:
    run_logger = get_run_logger()
    await run_in_threadpool(
        generate_plan_point_cloud, Path(splat_path), Path(colmap_directory)
    )
    run_logger.info("Generated plan point cloud for %s", splat_path)


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

    local_environment = LocalCommandExecutionEnvironment()
    gpu_execution_environment = (
        SCITAS_EXECUTION_ENVIRONMENT if config.USE_SCITAS else local_environment
    )

    frame_picker_settings = settings.frame_picker
    extraction_directory = (
        raw_frames_directory if frame_picker_settings is not None else frames_directory
    )
    extracted_frames_directory = await extract_frames_task(
        workspace_directory=workspace_directory,
        video_path=video_path,
        frames_directory=extraction_directory,
        fps=None if frame_picker_settings is not None else settings.ffmpeg.fps,
        fit_in_width=settings.ffmpeg.fit_in_width,
        fit_in_height=settings.ffmpeg.fit_in_height,
        execution_environment=local_environment,
        report_progress=_progress_callback(reconstruction_id, 0.05, 0.25),
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
        await pick_frames_task(
            workspace_directory=workspace_directory,
            video_path=video_path,
            input_frames_directory=extracted_frames_directory,
            frames_directory=frames_directory,
            settings=frame_picker_settings,
            report_progress=_progress_callback(reconstruction_id, 0.25, 0.40),
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
    geometry_settings = settings.spirula_geometry
    predicts_geometry_maps = (
        geometry_settings.compute_depth or geometry_settings.compute_normals
    )
    sfm_progress_start = 0.40
    masks_enabled = (
        settings.spirula_sfm.remove_objects.enabled
        or settings.spirula_train.keep_objects.enabled
    )
    if masks_enabled:
        await generate_masks_task(
            workspace_directory=workspace_directory,
            frames_directory=selected_frames_directory,
            remove_objects=settings.spirula_sfm.remove_objects,
            keep_objects=settings.spirula_train.keep_objects,
            execution_environment=gpu_execution_environment,
            report_progress=_progress_callback(reconstruction_id, 0.40, 0.50),
        )
        sfm_progress_start = 0.50
        await _record_reconstruction_progress(reconstruction_id, progress=0.50)
    sfm_progress_end = 0.65 if predicts_geometry_maps else 0.70
    reconstructed_colmap_directory = await reconstruct_with_spirula_task(
        workspace_directory=workspace_directory,
        frames_directory=selected_frames_directory,
        colmap_directory=colmap_directory,
        settings=settings.spirula_sfm,
        execution_environment=gpu_execution_environment,
        report_progress=_progress_callback(
            reconstruction_id, sfm_progress_start, sfm_progress_end
        ),
    )
    if predicts_geometry_maps:
        await _record_reconstruction_progress(reconstruction_id, progress=0.65)
        await predict_geometry_maps_task(
            workspace_directory=workspace_directory,
            dataset_directory=str(Path(reconstructed_colmap_directory).parent),
            settings=geometry_settings,
            execution_environment=gpu_execution_environment,
            report_progress=_progress_callback(reconstruction_id, 0.65, 0.70),
        )
    await _record_reconstruction_progress(
        reconstruction_id,
        progress=0.70,
        artifacts=ReconstructionArtifactUpdate(
            colmap_directory=reconstructed_colmap_directory,
        ),
    )
    generated_splat_path = await train_with_spirula_task(
        workspace_directory=workspace_directory,
        dataset_directory=str(Path(reconstructed_colmap_directory).parent),
        splat_path=splat_path,
        settings=settings.spirula_train,
        execution_environment=gpu_execution_environment,
        report_progress=_progress_callback(reconstruction_id, 0.70, 0.92),
    )
    await _record_reconstruction_progress(
        reconstruction_id,
        progress=0.92,
        artifacts=ReconstructionArtifactUpdate(splat_path=generated_splat_path),
    )
    await generate_plan_point_cloud_task(
        splat_path=splat_path,
        colmap_directory=colmap_directory,
    )
    await _record_reconstruction_progress(
        reconstruction_id,
        progress=0.95,
        artifacts=ReconstructionArtifactUpdate(splat_path=generated_splat_path),
    )
    return generated_splat_path


def _splat_generation_parameters(
    *,
    artifact: SplatGenerationArtifact,
    video_path: Path,
    settings: SplatGenerationWorkflowSettings,
    owner_id: UUID,
) -> dict[str, object]:
    return {
        "artifact_id": str(artifact.artifact_id),
        "workspace_directory": str(artifact.root_directory.resolve()),
        "video_path": str(video_path.resolve()),
        "raw_frames_directory": str(artifact.raw_frames_directory.resolve()),
        "frames_directory": str(artifact.frames_directory.resolve()),
        "colmap_directory": str(artifact.colmap_directory.resolve()),
        "splat_path": str(artifact.splat_path.resolve()),
        "settings": settings.model_dump(mode="json"),
        "owner_id": str(owner_id),
    }


async def _submit_splat_generation_run(
    parameters: dict[str, object],
    reconstruction_id: UUID | None = None,
) -> UUID:
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


async def schedule_splat_generation_from_upload(
    *,
    artifact: SplatGenerationArtifact,
    video_path: Path,
    settings: SplatGenerationWorkflowSettings,
    owner_id: UUID,
    reconstruction_id: UUID | None = None,
) -> UUID:
    """Schedule splat generation reading the permanent upload directly."""

    parameters: dict[str, object] = _splat_generation_parameters(
        artifact=artifact,
        video_path=video_path,
        settings=settings,
        owner_id=owner_id,
    )
    return await _submit_splat_generation_run(parameters, reconstruction_id)
