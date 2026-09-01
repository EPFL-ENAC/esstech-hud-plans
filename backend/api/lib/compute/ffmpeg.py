from pathlib import Path

from api.lib.utils.commands import (
    Command,
    CommandExecutionEnvironment,
    LogCallback,
    workspace_relative_path,
)


def build_frame_extraction_command(
    video_path: Path,
    frames_directory: Path,
    *,
    workspace_directory: Path,
    fps: float,
    fit_in_width: int,
    fit_in_height: int,
) -> Command:
    filters = (
        f"scale={fit_in_width}:{fit_in_height}:"
        f"force_original_aspect_ratio=decrease,fps={fps}"
    )
    relative_video_path = workspace_relative_path(video_path, workspace_directory)
    relative_frames_directory = workspace_relative_path(
        frames_directory, workspace_directory
    )
    output_pattern = relative_frames_directory / "frame_%05d.jpg"

    return Command(
        tool="ffmpeg",
        arguments=(
            "-nostdin",
            "-y",
            "-i",
            relative_video_path.as_posix(),
            "-vf",
            filters,
            "-q:v",
            "4",
            output_pattern.as_posix(),
        ),
        capture="stderr",
    )


def run_frame_extraction(
    video_path: Path,
    frames_directory: Path,
    *,
    workspace_directory: Path,
    execution_environment: CommandExecutionEnvironment,
    fps: float,
    fit_in_width: int,
    fit_in_height: int,
    on_log: LogCallback | None = None,
) -> Path:
    """Extract JPEG frames from a video and return their directory."""

    workspace_directory = workspace_directory.resolve()
    video_path = video_path.resolve()
    frames_directory = frames_directory.resolve()

    command = build_frame_extraction_command(
        video_path,
        frames_directory,
        workspace_directory=workspace_directory,
        fps=fps,
        fit_in_width=fit_in_width,
        fit_in_height=fit_in_height,
    )

    if not video_path.is_file():
        raise FileNotFoundError(f"Input video does not exist: {video_path}")

    frames_directory.mkdir(parents=True, exist_ok=True)
    execution_environment.execute(
        command,
        workspace=workspace_directory,
        on_log=on_log,
    )

    if not any(frames_directory.glob("frame_*.jpg")):
        raise RuntimeError("ffmpeg completed without producing any frames")

    return frames_directory
