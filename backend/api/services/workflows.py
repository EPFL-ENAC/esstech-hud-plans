import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from uuid import UUID, uuid4

from api.lib.compute.ffmpeg import run_frame_extraction
from api.models.workflows import FrameExtractionSettings
from prefect import flow, get_client, get_run_logger, task
from prefect.client.schemas.objects import FlowRun
from prefect.deployments import arun_deployment
from prefect.exceptions import ObjectNotFound

FRAME_EXTRACTION_DEPLOYMENT = "frame-extraction/default"
BACKEND_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DATA_DIRECTORY = BACKEND_ROOT / "data" / "workflows"


class WorkflowNotFoundError(Exception):
    pass


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

    @classmethod
    def create(cls, storage_root: Path, video_format: str = "mp4") -> Self:
        artifact = cls(uuid4(), storage_root, video_format)
        artifact.video_path.parent.mkdir(parents=True)
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
        fps=fps,
        fit_in_width=fit_in_width,
        fit_in_height=fit_in_height,
        on_log=log_ffmpeg,
    )
    return str(output_directory)


@flow(name="frame-extraction")
def frame_extraction_flow(
    artifact_id: UUID,
    video_path: str,
    frames_directory: str,
    fps: float,
    fit_in_width: int,
    fit_in_height: int,
    owner_id: str,
) -> str:
    if not owner_id:
        raise ValueError("owner_id must not be empty")

    run_logger = get_run_logger()
    run_logger.info("Starting frame extraction for artifact %s", artifact_id)
    return extract_frames_task(
        video_path=video_path,
        frames_directory=frames_directory,
        fps=fps,
        fit_in_width=fit_in_width,
        fit_in_height=fit_in_height,
    )


async def schedule_frame_extraction(
    artifact: FrameExtractionArtifact,
    settings: FrameExtractionSettings,
    owner_id: str,
) -> UUID:
    flow_run = await arun_deployment(
        name=FRAME_EXTRACTION_DEPLOYMENT,
        parameters={
            "artifact_id": str(artifact.artifact_id),
            "video_path": str(artifact.video_path.resolve()),
            "frames_directory": str(artifact.frames_directory.resolve()),
            "fps": settings.fps,
            "fit_in_width": settings.fit_in_width,
            "fit_in_height": settings.fit_in_height,
            "owner_id": owner_id,
        },
        timeout=0,
        as_subflow=False,
    )
    return flow_run.id


async def get_owned_workflow_run(workflow_id: UUID, owner_id: str) -> FlowRun:
    try:
        async with get_client() as client:
            flow_run = await client.read_flow_run(workflow_id)
    except ObjectNotFound as exc:
        raise WorkflowNotFoundError from exc

    if flow_run.parameters.get("owner_id") != owner_id:
        raise WorkflowNotFoundError

    return flow_run


def serve_workflows() -> None:
    frame_extraction_flow.serve(name="default", limit=1)


if __name__ == "__main__":
    serve_workflows()
