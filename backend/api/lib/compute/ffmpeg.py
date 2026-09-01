import logging
import shutil
from pathlib import Path

from api.lib.utils.commands import LogCallback, run_logged_command

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
FFMPEG_COMMAND = BACKEND_ROOT / "external" / "bin" / "ffmpeg"


def _resolve_ffmpeg_command() -> str:
    if FFMPEG_COMMAND.is_file():
        return str(FFMPEG_COMMAND)

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg is not None:
        return system_ffmpeg

    raise FileNotFoundError("ffmpeg executable was not found")


def build_frame_extraction_command(
    video_path: Path,
    frames_directory: Path,
    *,
    fps: float,
    fit_in_width: int,
    fit_in_height: int,
) -> list[str]:
    filters = (
        f"scale={fit_in_width}:{fit_in_height}:"
        f"force_original_aspect_ratio=decrease,fps={fps}"
    )
    output_pattern = frames_directory / "frame_%05d.jpg"

    return [
        _resolve_ffmpeg_command(),
        "-nostdin",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        filters,
        "-q:v",
        "4",
        str(output_pattern),
    ]


def run_frame_extraction(
    video_path: Path,
    frames_directory: Path,
    *,
    fps: float,
    fit_in_width: int,
    fit_in_height: int,
    on_log: LogCallback | None = None,
) -> Path:
    """Extract JPEG frames from a video and return their directory."""

    video_path = video_path.resolve()
    frames_directory = frames_directory.resolve()

    if not video_path.is_file():
        raise FileNotFoundError(f"Input video does not exist: {video_path}")

    frames_directory.mkdir(parents=True, exist_ok=True)
    command = build_frame_extraction_command(
        video_path,
        frames_directory,
        fps=fps,
        fit_in_width=fit_in_width,
        fit_in_height=fit_in_height,
    )

    run_logged_command(
        command,
        capture="stderr",
        log_prefix="ffmpeg",
        fallback_logger=logger,
        on_log=on_log,
    )

    if not any(frames_directory.glob("frame_*.jpg")):
        raise RuntimeError("ffmpeg completed without producing any frames")

    return frames_directory
