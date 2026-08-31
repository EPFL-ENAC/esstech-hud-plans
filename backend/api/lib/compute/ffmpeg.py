import codecs
import logging
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
FFMPEG_COMMAND = BACKEND_ROOT / "external" / "bin" / "ffmpeg"
LogCallback = Callable[[str], None]


class BinaryReadStream(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


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


def iter_ffmpeg_log_records(stream: BinaryReadStream) -> Iterator[str]:
    """Yield UTF-8 ffmpeg records delimited by newlines or carriage returns."""

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    record_parts: list[str] = []

    def consume(text: str) -> Iterator[str]:
        for character in text:
            if character in "\r\n":
                record = "".join(record_parts).rstrip()
                record_parts.clear()
                if record:
                    yield record
            else:
                record_parts.append(character)

    while chunk := stream.read(4096):
        yield from consume(decoder.decode(chunk))

    yield from consume(decoder.decode(b"", final=True))
    final_record = "".join(record_parts).rstrip()
    if final_record:
        yield final_record


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

    logger.info("Running frame extraction: %s", command)
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    emit_log = on_log or (lambda record: logger.info("ffmpeg: %s", record))
    try:
        assert process.stderr is not None
        for record in iter_ffmpeg_log_records(process.stderr):
            emit_log(record)
    except BaseException:
        if process.poll() is None:
            process.terminate()
        process.wait()
        raise

    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)

    if not any(frames_directory.glob("frame_*.jpg")):
        raise RuntimeError("ffmpeg completed without producing any frames")

    return frames_directory
