from pathlib import Path

import pytest
from api.lib.compute import colmap
from api.lib.utils.commands import (
    Command,
    CommandExecutionEnvironment,
    CommandResult,
    LogCallback,
)
from api.models.workflows import ColmapSettings


class _NoOpEnvironment(CommandExecutionEnvironment):
    def execute(
        self,
        command: Command,
        *,
        workspace: Path,
        on_log: LogCallback | None = None,
    ) -> CommandResult:
        return CommandResult(return_code=0)


def _create_frame(frames_directory: Path) -> None:
    frames_directory.mkdir(parents=True)
    (frames_directory / "frame_00001.jpg").touch()


def _create_sparse_model(colmap_directory: Path) -> None:
    model_directory = colmap_directory / "sparse" / "0"
    model_directory.mkdir(parents=True, exist_ok=True)
    for filename in ("cameras.bin", "images.bin", "points3D.bin"):
        (model_directory / filename).touch()


def test_build_colmap_command_uses_workspace_relative_paths_and_global_mapper(
    tmp_path: Path,
) -> None:
    frames_directory = tmp_path / "input frames"
    colmap_directory = tmp_path / "COLMAP workspace"

    command = colmap.build_colmap_command(
        frames_directory,
        colmap_directory,
        ColmapSettings(
            data_type="internet",
            quality="high",
            camera_model="RADIAL",
            single_camera=False,
            use_gpu=True,
            use_global_mapper=True,
        ),
        workspace_directory=tmp_path,
    )

    assert command == Command(
        tool="colmap",
        arguments=(
            "automatic_reconstructor",
            "--image_path",
            "input frames",
            "--workspace_path",
            "COLMAP workspace",
            "--camera_model",
            "RADIAL",
            "--dense",
            "0",
            "--data_type",
            "internet",
            "--quality",
            "high",
            "--single_camera",
            "0",
            "--use_gpu",
            "1",
            "--mapper",
            "global",
        ),
        capture="combined",
    )


def test_build_colmap_command_rejects_paths_outside_workspace(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="must be inside workspace"):
        colmap.build_colmap_command(
            tmp_path.parent / "frames",
            tmp_path / "colmap",
            ColmapSettings(),
            workspace_directory=tmp_path,
        )


def test_run_colmap_reconstruction_uses_combined_logs_and_returns_workspace(
    tmp_path: Path,
) -> None:
    frames_directory = tmp_path / "frames"
    colmap_directory = tmp_path / "colmap"
    _create_frame(frames_directory)
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
            on_log("feature extraction")
            on_log("mapping")
            _create_sparse_model(colmap_directory)
            return CommandResult(return_code=0)

    records: list[str] = []
    on_log = records.append

    result = colmap.run_colmap_reconstruction(
        frames_directory,
        colmap_directory,
        ColmapSettings(),
        workspace_directory=tmp_path,
        execution_environment=FakeEnvironment(),
        on_log=on_log,
    )

    assert result == colmap_directory.resolve()
    assert records == ["feature extraction", "mapping"]
    command = captured["command"]
    gpu_option_index = command.arguments.index("--use_gpu")
    assert command.arguments[gpu_option_index + 1] == "0"
    assert command.capture == "combined"
    assert captured["workspace"] == tmp_path.resolve()
    assert captured["on_log"] is on_log


def test_run_colmap_reconstruction_requires_frames(tmp_path: Path) -> None:
    frames_directory = tmp_path / "frames"
    frames_directory.mkdir()

    with pytest.raises(RuntimeError, match="contains no JPEG frames"):
        colmap.run_colmap_reconstruction(
            frames_directory,
            tmp_path / "colmap",
            ColmapSettings(),
            workspace_directory=tmp_path,
            execution_environment=_NoOpEnvironment(),
        )


def test_run_colmap_reconstruction_requires_valid_sparse_model(
    tmp_path: Path,
) -> None:
    frames_directory = tmp_path / "frames"
    _create_frame(frames_directory)
    with pytest.raises(RuntimeError, match="valid sparse/0 reconstruction"):
        colmap.run_colmap_reconstruction(
            frames_directory,
            tmp_path / "colmap",
            ColmapSettings(),
            workspace_directory=tmp_path,
            execution_environment=_NoOpEnvironment(),
        )
