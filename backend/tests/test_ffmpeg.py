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


def test_run_frame_extraction_uses_logged_stderr_and_returns_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"not a real video")
    frames_directory = tmp_path / "frames"
    monkeypatch.setattr(ffmpeg, "_resolve_ffmpeg_command", lambda: "ffmpeg")
    records: list[str] = []
    on_log = records.append
    captured: dict = {}

    def fake_run_logged_command(command, **kwargs) -> None:
        captured["command"] = command
        captured.update(kwargs)
        kwargs["on_log"]("frame=1")
        kwargs["on_log"]("frame=2")
        (frames_directory / "frame_00001.jpg").touch()

    monkeypatch.setattr(ffmpeg, "run_logged_command", fake_run_logged_command)
    result = ffmpeg.run_frame_extraction(
        video_path,
        frames_directory,
        fps=2,
        fit_in_width=100,
        fit_in_height=100,
        on_log=on_log,
    )

    assert result == frames_directory.resolve()
    assert records == ["frame=1", "frame=2"]
    assert captured["capture"] == "stderr"
    assert captured["log_prefix"] == "ffmpeg"
    assert captured["fallback_logger"] is ffmpeg.logger
    assert captured["on_log"] is on_log


def test_run_frame_extraction_requires_at_least_one_frame(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"not a real video")
    monkeypatch.setattr(ffmpeg, "_resolve_ffmpeg_command", lambda: "ffmpeg")
    monkeypatch.setattr(ffmpeg, "run_logged_command", lambda *args, **kwargs: None)

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
