import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from uuid import UUID, uuid4

from api.config import config
from api.lib.compute.brush import run_brush_training
from api.lib.compute.colmap import run_colmap_reconstruction
from api.lib.compute.evaluate_video_frame import pick_frames
from api.lib.compute.ffmpeg import run_frame_extraction
from api.lib.utils.commands import (
    CommandExecutionEnvironment,
    LocalCommandExecutionEnvironment,
    ScitasCommandExecutionEnvironment,
)
from api.models.workflows import (
    BrushSettings,
    ColmapSettings,
    FramePickerSettings,
    SplatGenerationWorkflowSettings,
)
from fastapi import UploadFile
from prefect import flow, get_run_logger, task
from prefect.client.schemas.objects import FlowRun
from prefect.deployments import arun_deployment
from starlette.concurrency import run_in_threadpool

SPLAT_GENERATION_DEPLOYMENT = "splat-generation/default"
LOCAL_EXECUTION_ENVIRONMENT = LocalCommandExecutionEnvironment()
SCITAS_EXECUTION_ENVIRONMENT = ScitasCommandExecutionEnvironment()


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
    def create(cls, storage_root: Path, video_format: str = "mp4") -> Self:
        artifact = cls(uuid4(), storage_root, video_format)
        artifact.video_path.parent.mkdir(parents=True)
        return artifact

    @classmethod
    async def from_uploaded_file(
        cls, uploaded_file: UploadFile, storage_root: Path
    ) -> Self:
        if not uploaded_file.filename:
            raise ValueError("Uploaded file must have a filename")

        file_extension = (
            Path(uploaded_file.filename).suffix.removeprefix(".").lower() or "mp4"
        )
        artifact = cls.create(storage_root, video_format=file_extension)

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


@flow(name="splat-generation")
def splat_generation_flow(
    artifact_id: UUID,
    workspace_directory: str,
    video_path: str,
    raw_frames_directory: str,
    frames_directory: str,
    colmap_directory: str,
    splat_path: str,
    settings: SplatGenerationWorkflowSettings,
    owner_id: str,
) -> str:
    if not owner_id:
        raise ValueError("owner_id must not be empty")

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
    reconstructed_colmap_directory = reconstruct_with_colmap_task(
        workspace_directory=workspace_directory,
        frames_directory=selected_frames_directory,
        colmap_directory=colmap_directory,
        settings=settings.colmap,
        execution_environment=gpu_execution_environment,
    )
    return train_with_brush_task(
        workspace_directory=workspace_directory,
        dataset_directory=str(Path(reconstructed_colmap_directory).parent),
        splat_path=splat_path,
        settings=settings.brush,
        execution_environment=gpu_execution_environment,
    )


async def schedule_splat_generation(
    artifact: SplatGenerationArtifact,
    settings: SplatGenerationWorkflowSettings,
    owner_id: str,
) -> UUID:
    flow_run = await arun_deployment(
        name=SPLAT_GENERATION_DEPLOYMENT,
        parameters={
            "artifact_id": str(artifact.artifact_id),
            "workspace_directory": str(artifact.root_directory.resolve()),
            "video_path": str(artifact.video_path.resolve()),
            "raw_frames_directory": str(artifact.raw_frames_directory.resolve()),
            "frames_directory": str(artifact.frames_directory.resolve()),
            "colmap_directory": str(artifact.colmap_directory.resolve()),
            "splat_path": str(artifact.splat_path.resolve()),
            "settings": settings.model_dump(mode="json"),
            "owner_id": owner_id,
        },
        timeout=0,
        as_subflow=False,
    )
    return flow_run.id
