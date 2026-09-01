import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from uuid import UUID, uuid4

from api.lib.compute.colmap import run_colmap_reconstruction
from api.lib.compute.ffmpeg import run_frame_extraction
from api.lib.utils.commands import LocalCommandExecutionEnvironment
from api.models.workflows import ColmapSettings, FrameExtractionWorkflowSettings
from fastapi import UploadFile
from prefect import flow, get_run_logger, task
from prefect.client.schemas.objects import FlowRun
from prefect.deployments import arun_deployment
from starlette.concurrency import run_in_threadpool

FRAME_EXTRACTION_DEPLOYMENT = "frame-extraction/default"
LOCAL_EXECUTION_ENVIRONMENT = LocalCommandExecutionEnvironment()


@dataclass(frozen=True)
class FrameExtractionArtifact:
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
    def colmap_directory(self) -> Path:
        return self.root_directory / "colmap"

    @property
    def colmap_sparse_directory(self) -> Path:
        return self.colmap_directory / "sparse" / "0"

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
    fps: float,
    fit_in_width: int,
    fit_in_height: int,
) -> str:
    run_logger = get_run_logger()

    def log_ffmpeg(record: str) -> None:
        run_logger.info("ffmpeg: %s", record)

    output_directory = run_frame_extraction(
        Path(video_path),
        Path(frames_directory),
        workspace_directory=Path(workspace_directory),
        execution_environment=LOCAL_EXECUTION_ENVIRONMENT,
        fps=fps,
        fit_in_width=fit_in_width,
        fit_in_height=fit_in_height,
        on_log=log_ffmpeg,
    )
    return str(output_directory)


@task(name="reconstruct-with-colmap")
def reconstruct_with_colmap_task(
    workspace_directory: str,
    frames_directory: str,
    colmap_directory: str,
    settings: ColmapSettings,
) -> str:
    run_logger = get_run_logger()

    def log_colmap(record: str) -> None:
        run_logger.info("colmap: %s", record)

    output_directory = run_colmap_reconstruction(
        Path(frames_directory),
        Path(colmap_directory),
        settings,
        workspace_directory=Path(workspace_directory),
        execution_environment=LOCAL_EXECUTION_ENVIRONMENT,
        on_log=log_colmap,
    )
    return str(output_directory)


@flow(name="frame-extraction")
def frame_extraction_flow(
    artifact_id: UUID,
    workspace_directory: str,
    video_path: str,
    frames_directory: str,
    colmap_directory: str,
    settings: FrameExtractionWorkflowSettings,
    owner_id: str,
) -> str:
    if not owner_id:
        raise ValueError("owner_id must not be empty")

    run_logger = get_run_logger()
    run_logger.info("Starting frame extraction for artifact %s", artifact_id)
    extracted_frames_directory = extract_frames_task(
        workspace_directory=workspace_directory,
        video_path=video_path,
        frames_directory=frames_directory,
        fps=settings.ffmpeg.fps,
        fit_in_width=settings.ffmpeg.fit_in_width,
        fit_in_height=settings.ffmpeg.fit_in_height,
    )
    return reconstruct_with_colmap_task(
        workspace_directory=workspace_directory,
        frames_directory=extracted_frames_directory,
        colmap_directory=colmap_directory,
        settings=settings.colmap,
    )


async def schedule_frame_extraction(
    artifact: FrameExtractionArtifact,
    settings: FrameExtractionWorkflowSettings,
    owner_id: str,
) -> UUID:
    flow_run = await arun_deployment(
        name=FRAME_EXTRACTION_DEPLOYMENT,
        parameters={
            "artifact_id": str(artifact.artifact_id),
            "workspace_directory": str(artifact.root_directory.resolve()),
            "video_path": str(artifact.video_path.resolve()),
            "frames_directory": str(artifact.frames_directory.resolve()),
            "colmap_directory": str(artifact.colmap_directory.resolve()),
            "settings": settings.model_dump(mode="json"),
            "owner_id": owner_id,
        },
        timeout=0,
        as_subflow=False,
    )
    return flow_run.id
