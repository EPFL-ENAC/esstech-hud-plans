from pathlib import Path

import pytest
from api.lib.compute import brush
from api.lib.utils.commands import (
    Command,
    CommandExecutionEnvironment,
    CommandResult,
    LogCallback,
)
from api.models.workflows import BrushSettings


class _NoOpEnvironment(CommandExecutionEnvironment):
    def execute(
        self,
        command: Command,
        *,
        workspace: Path,
        on_log: LogCallback | None = None,
    ) -> CommandResult:
        return CommandResult(return_code=0)


def _create_brush_dataset(dataset_directory: Path) -> None:
    frames_directory = dataset_directory / "frames"
    frames_directory.mkdir(parents=True)
    (frames_directory / "frame_00001.jpg").touch()

    sparse_directory = dataset_directory / "colmap" / "sparse" / "0"
    sparse_directory.mkdir(parents=True)
    for filename in ("cameras.bin", "images.bin", "points3D.bin"):
        (sparse_directory / filename).touch()


def test_build_brush_command_uses_workspace_relative_paths_and_settings(
    tmp_path: Path,
) -> None:
    dataset_directory = tmp_path / "dataset"
    splat_path = tmp_path / "outputs" / "scene.ply"

    command = brush.build_brush_command(
        dataset_directory,
        splat_path,
        BrushSettings(
            total_steps=20_000,
            render_mode="mip",
            sh_degree=2,
            max_splats=2_000_000,
            refine_every=100,
            growth_grad_threshold=0.005,
            growth_stop_iter=12_000,
            max_resolution=1280,
            subsample_frames=2,
            alpha_mode="masked",
            export_every=2_500,
        ),
        workspace_directory=tmp_path,
    )

    assert command == Command(
        tool="brush",
        arguments=(
            "dataset",
            "--export-path",
            "outputs",
            "--export-name",
            "scene.ply",
            "--total-train-iters",
            "20000",
            "--render-mode",
            "mip",
            "--sh-degree",
            "2",
            "--max-splats",
            "2000000",
            "--refine-every",
            "100",
            "--growth-grad-threshold",
            "0.005",
            "--growth-stop-iter",
            "12000",
            "--max-resolution",
            "1280",
            "--subsample-frames",
            "2",
            "--alpha-mode",
            "masked",
            "--export-every",
            "2500",
        ),
        capture="combined",
    )


def test_build_brush_command_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must be inside workspace"):
        brush.build_brush_command(
            tmp_path.parent / "dataset",
            tmp_path / "splat.ply",
            BrushSettings(),
            workspace_directory=tmp_path,
        )


def test_run_brush_training_forwards_logs_and_returns_splat(tmp_path: Path) -> None:
    _create_brush_dataset(tmp_path)
    splat_path = tmp_path / "splat.ply"
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
            on_log("step 1/10000")
            on_log("exporting splat")
            splat_path.touch()
            return CommandResult(return_code=0)

    records: list[str] = []
    on_log = records.append
    result = brush.run_brush_training(
        tmp_path,
        splat_path,
        BrushSettings(),
        workspace_directory=tmp_path,
        execution_environment=FakeEnvironment(),
        on_log=on_log,
    )

    assert result == splat_path.resolve()
    assert records == ["step 1/10000", "exporting splat"]
    assert captured["command"].capture == "combined"
    assert captured["command"].arguments[:5] == (
        ".",
        "--export-path",
        ".",
        "--export-name",
        "splat.ply",
    )
    assert captured["workspace"] == tmp_path.resolve()
    assert captured["on_log"] is on_log


@pytest.mark.parametrize(
    ("missing_path", "message"),
    [
        ("frames", "no extracted JPEG frames"),
        ("colmap", "no COLMAP sparse reconstruction"),
    ],
)
def test_run_brush_training_requires_complete_dataset(
    tmp_path: Path, missing_path: str, message: str
) -> None:
    _create_brush_dataset(tmp_path)
    if missing_path == "frames":
        (tmp_path / "frames" / "frame_00001.jpg").unlink()
    else:
        for path in (tmp_path / "colmap" / "sparse" / "0").iterdir():
            path.unlink()
        (tmp_path / "colmap" / "sparse" / "0").rmdir()

    with pytest.raises(RuntimeError, match=message):
        brush.run_brush_training(
            tmp_path,
            tmp_path / "splat.ply",
            BrushSettings(),
            workspace_directory=tmp_path,
            execution_environment=_NoOpEnvironment(),
        )


def test_run_brush_training_requires_generated_splat(tmp_path: Path) -> None:
    _create_brush_dataset(tmp_path)

    with pytest.raises(RuntimeError, match="expected splat PLY"):
        brush.run_brush_training(
            tmp_path,
            tmp_path / "splat.ply",
            BrushSettings(),
            workspace_directory=tmp_path,
            execution_environment=_NoOpEnvironment(),
        )
