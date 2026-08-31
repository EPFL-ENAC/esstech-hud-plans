import io
import shutil
import subprocess
from pathlib import Path

import cv2
import pytest
from api.lib.compute import ffmpeg


def test_build_frame_extraction_command_handles_paths_with_spaces(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(ffmpeg, "_resolve_ffmpeg_command", lambda: "/ffmpeg bin")
    video_path = tmp_path / "source videos" / "input video.mp4"
    frames_directory = tmp_path / "output frames"

    command = ffmpeg.build_frame_extraction_command(
        video_path,
        frames_directory,
        fps=2.5,
        fit_in_width=1920,
        fit_in_height=1080,
    )

    assert command == [
        "/ffmpeg bin",
        "-nostdin",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=decrease,fps=2.5",
        "-q:v",
        "4",
        str(frames_directory / "frame_%05d.jpg"),
    ]


class _FakeProcess:
    def __init__(self, return_code: int, output: bytes = b"ffmpeg output\n"):
        self.return_code = return_code
        self.stderr = io.BytesIO(output)
        self.waited = False
        self.terminated = False

    def wait(self) -> int:
        self.waited = True
        return self.return_code

    def poll(self) -> int | None:
        return self.return_code if self.waited else None

    def terminate(self) -> None:
        self.terminated = True


class _ChunkedStream:
    def __init__(self, chunks: list[bytes]):
        self.chunks = iter(chunks)

    def read(self, size: int = -1) -> bytes:
        return next(self.chunks, b"")


def test_iter_ffmpeg_log_records_normalizes_stream_boundaries() -> None:
    stream = _ChunkedStream(
        [
            b"header\nframe=1\r\n\r",
            b"caf\xc3",
            b"\xa9\nfinal record",
        ]
    )

    assert list(ffmpeg.iter_ffmpeg_log_records(stream)) == [
        "header",
        "frame=1",
        "caf\u00e9",
        "final record",
    ]


def test_run_frame_extraction_emits_logs_before_waiting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"not a real video")
    frames_directory = tmp_path / "frames"
    process = _FakeProcess(0, b"frame=1\rframe=2\r")
    monkeypatch.setattr(ffmpeg.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(ffmpeg, "_resolve_ffmpeg_command", lambda: "ffmpeg")
    records: list[str] = []

    def on_log(record: str) -> None:
        assert not process.waited
        records.append(record)
        (frames_directory / "frame_00001.jpg").touch()

    ffmpeg.run_frame_extraction(
        video_path,
        frames_directory,
        fps=2,
        fit_in_width=100,
        fit_in_height=100,
        on_log=on_log,
    )

    assert records == ["frame=1", "frame=2"]
    assert process.waited


def test_run_frame_extraction_raises_on_ffmpeg_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"not a real video")
    process = _FakeProcess(1, b"first line\nlast progress\r")
    monkeypatch.setattr(ffmpeg.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(ffmpeg, "_resolve_ffmpeg_command", lambda: "ffmpeg")
    records: list[str] = []

    with pytest.raises(subprocess.CalledProcessError):
        ffmpeg.run_frame_extraction(
            video_path,
            tmp_path / "frames",
            fps=2,
            fit_in_width=100,
            fit_in_height=100,
            on_log=records.append,
        )

    assert records == ["first line", "last progress"]


def test_run_frame_extraction_terminates_process_when_logging_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"not a real video")
    process = _FakeProcess(0)
    monkeypatch.setattr(ffmpeg.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(ffmpeg, "_resolve_ffmpeg_command", lambda: "ffmpeg")

    def fail_to_log(record: str) -> None:
        raise RuntimeError(f"Could not log: {record}")

    with pytest.raises(RuntimeError, match="Could not log"):
        ffmpeg.run_frame_extraction(
            video_path,
            tmp_path / "frames",
            fps=2,
            fit_in_width=100,
            fit_in_height=100,
            on_log=fail_to_log,
        )

    assert process.terminated
    assert process.waited


def test_run_frame_extraction_requires_at_least_one_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"not a real video")
    monkeypatch.setattr(
        ffmpeg.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess(0)
    )
    monkeypatch.setattr(ffmpeg, "_resolve_ffmpeg_command", lambda: "ffmpeg")

    with pytest.raises(RuntimeError, match="without producing any frames"):
        ffmpeg.run_frame_extraction(
            video_path,
            tmp_path / "frames",
            fps=2,
            fit_in_width=100,
            fit_in_height=100,
        )


def _ffmpeg_is_available() -> bool:
    return ffmpeg.FFMPEG_COMMAND.is_file() or shutil.which("ffmpeg") is not None


@pytest.mark.skipif(not _ffmpeg_is_available(), reason="ffmpeg is not installed")
def test_run_frame_extraction_with_real_ffmpeg(tmp_path: Path) -> None:
    working_directory = tmp_path / "directory with spaces"
    working_directory.mkdir()
    video_path = working_directory / "input video.mp4"
    frames_directory = working_directory / "output frames"
    ffmpeg_command = ffmpeg._resolve_ffmpeg_command()

    subprocess.run(
        [
            ffmpeg_command,
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x48:d=1:r=4",
            "-c:v",
            "mpeg4",
            str(video_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    records: list[str] = []
    result = ffmpeg.run_frame_extraction(
        video_path,
        frames_directory,
        fps=2,
        fit_in_width=32,
        fit_in_height=32,
        on_log=records.append,
    )

    frames = sorted(result.glob("frame_*.jpg"))
    assert [frame.name for frame in frames] == ["frame_00001.jpg", "frame_00002.jpg"]
    image = cv2.imread(str(frames[0]))
    assert image is not None
    assert image.shape[:2] == (24, 32)
    assert any(record.startswith("frame=") for record in records)
