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
    def __init__(self, return_code: int):
        self.return_code = return_code
        self.stderr = iter(["ffmpeg output\n"])

    def wait(self) -> int:
        return self.return_code


def test_run_frame_extraction_raises_on_ffmpeg_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"not a real video")
    monkeypatch.setattr(
        ffmpeg.subprocess, "Popen", lambda *args, **kwargs: _FakeProcess(1)
    )
    monkeypatch.setattr(ffmpeg, "_resolve_ffmpeg_command", lambda: "ffmpeg")

    with pytest.raises(subprocess.CalledProcessError):
        ffmpeg.run_frame_extraction(
            video_path,
            tmp_path / "frames",
            fps=2,
            fit_in_width=100,
            fit_in_height=100,
        )


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

    result = ffmpeg.run_frame_extraction(
        video_path,
        frames_directory,
        fps=2,
        fit_in_width=32,
        fit_in_height=32,
    )

    frames = sorted(result.glob("frame_*.jpg"))
    assert [frame.name for frame in frames] == ["frame_00001.jpg", "frame_00002.jpg"]
    image = cv2.imread(str(frames[0]))
    assert image is not None
    assert image.shape[:2] == (24, 32)
