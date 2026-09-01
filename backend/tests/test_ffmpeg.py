import shutil
import subprocess
from pathlib import Path

import cv2
import pytest
from api.lib.compute import ffmpeg
from api.lib.utils.commands import (
    LOCAL_EXECUTABLES_DIRECTORY,
    Command,
    CommandExecutionEnvironment,
    CommandResult,
    LocalCommandExecutionEnvironment,
    LogCallback,
)


def test_build_frame_extraction_command_uses_workspace_relative_paths(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "source videos" / "input video.mp4"
    frames_directory = tmp_path / "output frames"

    command = ffmpeg.build_frame_extraction_command(
        video_path,
        frames_directory,
        workspace_directory=tmp_path,
        fps=2.5,
        fit_in_width=1920,
        fit_in_height=1080,
    )

    assert command == Command(
        tool="ffmpeg",
        arguments=(
            "-nostdin",
            "-y",
            "-i",
            "source videos/input video.mp4",
            "-vf",
            "scale=1920:1080:force_original_aspect_ratio=decrease,fps=2.5",
            "-q:v",
            "4",
            "output frames/frame_%05d.jpg",
        ),
        capture="stderr",
    )


def test_build_frame_extraction_command_rejects_paths_outside_workspace(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must be inside workspace"):
        ffmpeg.build_frame_extraction_command(
            tmp_path.parent / "input.mp4",
            tmp_path / "frames",
            workspace_directory=tmp_path,
            fps=2,
            fit_in_width=100,
            fit_in_height=100,
        )


def test_run_frame_extraction_uses_logged_stderr_and_returns_frames(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"not a real video")
    frames_directory = tmp_path / "frames"
    records: list[str] = []
    on_log = records.append
    captured: dict = {}

    class FakeEnvironment(CommandExecutionEnvironment):
        def execute(
            self,
            command: Command,
            *,
            workspace: Path,
            on_log: LogCallback | None = None,
        ) -> CommandResult:
            captured["command"] = command
            captured["workspace"] = workspace
            captured["on_log"] = on_log
            assert on_log is not None
            on_log("frame=1")
            on_log("frame=2")
            (frames_directory / "frame_00001.jpg").touch()
            return CommandResult(return_code=0)

    result = ffmpeg.run_frame_extraction(
        video_path,
        frames_directory,
        workspace_directory=tmp_path,
        execution_environment=FakeEnvironment(),
        fps=2,
        fit_in_width=100,
        fit_in_height=100,
        on_log=on_log,
    )

    assert result == frames_directory.resolve()
    assert records == ["frame=1", "frame=2"]
    assert captured["command"].capture == "stderr"
    assert captured["workspace"] == tmp_path.resolve()
    assert captured["on_log"] is on_log


def test_run_frame_extraction_requires_at_least_one_frame(
    tmp_path: Path,
) -> None:
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"not a real video")

    class FakeEnvironment(CommandExecutionEnvironment):
        def execute(
            self,
            command: Command,
            *,
            workspace: Path,
            on_log: LogCallback | None = None,
        ) -> CommandResult:
            return CommandResult(return_code=0)

    with pytest.raises(RuntimeError, match="without producing any frames"):
        ffmpeg.run_frame_extraction(
            video_path,
            tmp_path / "frames",
            workspace_directory=tmp_path,
            execution_environment=FakeEnvironment(),
            fps=2,
            fit_in_width=100,
            fit_in_height=100,
        )


def _ffmpeg_is_available() -> bool:
    return (LOCAL_EXECUTABLES_DIRECTORY / "ffmpeg").is_file() or shutil.which(
        "ffmpeg"
    ) is not None


@pytest.mark.skipif(not _ffmpeg_is_available(), reason="ffmpeg is not installed")
def test_run_frame_extraction_with_real_ffmpeg(tmp_path: Path) -> None:
    working_directory = tmp_path / "directory with spaces"
    working_directory.mkdir()
    video_path = working_directory / "input video.mp4"
    frames_directory = working_directory / "output frames"
    environment = LocalCommandExecutionEnvironment()
    ffmpeg_command = environment._resolve_tool("ffmpeg")

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
        workspace_directory=working_directory,
        execution_environment=environment,
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
