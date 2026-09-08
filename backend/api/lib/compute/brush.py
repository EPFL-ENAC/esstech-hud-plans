from pathlib import Path

from api.lib.utils.commands import (
    Command,
    CommandExecutionEnvironment,
    LogCallback,
    workspace_relative_path,
)
from api.models.workflows import BrushSettings


def build_brush_command(
    dataset_directory: Path,
    splat_path: Path,
    settings: BrushSettings,
    *,
    workspace_directory: Path,
) -> Command:
    relative_dataset_directory = workspace_relative_path(
        dataset_directory, workspace_directory
    )
    relative_splat_path = workspace_relative_path(splat_path, workspace_directory)
    export_directory = relative_splat_path.parent

    return Command(
        tool="brush",
        arguments=(
            relative_dataset_directory.as_posix(),
            "--export-path",
            export_directory.as_posix(),
            "--export-name",
            relative_splat_path.name,
            "--total-train-iters",
            str(settings.total_steps),
            "--render-mode",
            settings.render_mode,
            "--sh-degree",
            str(settings.sh_degree),
            "--max-splats",
            str(settings.max_splats),
            "--refine-every",
            str(settings.refine_every),
            "--growth-grad-threshold",
            str(settings.growth_grad_threshold),
            "--growth-stop-iter",
            str(settings.growth_stop_iter),
            "--max-resolution",
            str(settings.max_resolution),
            "--subsample-frames",
            str(settings.subsample_frames),
            "--alpha-mode",
            settings.alpha_mode,
            "--export-every",
            str(settings.export_every),
        ),
        capture="combined",
    )


def _validate_brush_dataset(dataset_directory: Path) -> None:
    frames_directory = dataset_directory / "frames"
    if not frames_directory.is_dir() or not any(frames_directory.glob("frame_*.jpg")):
        raise RuntimeError(
            f"Brush dataset contains no extracted JPEG frames: {frames_directory}"
        )

    sparse_directory = dataset_directory / "colmap" / "sparse" / "0"
    if not sparse_directory.is_dir():
        raise RuntimeError(
            f"Brush dataset contains no COLMAP sparse reconstruction: {sparse_directory}"
        )

    filenames = {path.name for path in sparse_directory.iterdir() if path.is_file()}
    binary_model = {"cameras.bin", "images.bin", "points3D.bin"}
    text_model = {"cameras.txt", "images.txt", "points3D.txt"}
    if not (binary_model.issubset(filenames) or text_model.issubset(filenames)):
        raise RuntimeError(
            "Brush dataset contains no valid COLMAP sparse/0 reconstruction"
        )


def run_brush_training(
    dataset_directory: Path,
    splat_path: Path,
    settings: BrushSettings,
    *,
    workspace_directory: Path,
    execution_environment: CommandExecutionEnvironment,
    on_log: LogCallback | None = None,
) -> Path:
    """Train a Gaussian splat and return the generated PLY path."""

    workspace_directory = workspace_directory.resolve()
    dataset_directory = dataset_directory.resolve()
    splat_path = splat_path.resolve()

    command = build_brush_command(
        dataset_directory,
        splat_path,
        settings,
        workspace_directory=workspace_directory,
    )
    _validate_brush_dataset(dataset_directory)
    splat_path.parent.mkdir(parents=True, exist_ok=True)

    execution_environment.execute(
        command,
        workspace=workspace_directory,
        on_log=on_log,
    )

    if not splat_path.is_file():
        raise RuntimeError("Brush completed without producing the expected splat PLY")

    return splat_path
