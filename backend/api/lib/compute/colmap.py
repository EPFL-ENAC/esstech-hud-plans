from pathlib import Path

from api.lib.utils.commands import (
    Command,
    CommandExecutionEnvironment,
    LogCallback,
    workspace_relative_path,
)
from api.models.workflows import ColmapSettings


def build_colmap_command(
    frames_directory: Path,
    colmap_directory: Path,
    settings: ColmapSettings,
    *,
    workspace_directory: Path,
) -> Command:
    relative_frames_directory = workspace_relative_path(
        frames_directory, workspace_directory
    )
    relative_colmap_directory = workspace_relative_path(
        colmap_directory, workspace_directory
    )
    arguments = [
        "automatic_reconstructor",
        "--image_path",
        relative_frames_directory.as_posix(),
        "--workspace_path",
        relative_colmap_directory.as_posix(),
        "--camera_model",
        settings.camera_model,
        "--dense",
        "0",
        "--data_type",
        settings.data_type,
        "--quality",
        settings.quality,
        "--single_camera",
        "1" if settings.single_camera else "0",
        "--use_gpu",
        "1" if settings.use_gpu else "0",
    ]
    if settings.use_global_mapper:
        arguments.extend(["--mapper", "global"])
    return Command(tool="colmap", arguments=tuple(arguments), capture="combined")


def _looks_like_colmap_model(directory: Path) -> bool:
    if not directory.is_dir():
        return False

    filenames = {path.name for path in directory.iterdir() if path.is_file()}
    binary_model = {"cameras.bin", "images.bin", "points3D.bin"}
    text_model = {"cameras.txt", "images.txt", "points3D.txt"}
    return binary_model.issubset(filenames) or text_model.issubset(filenames)


def run_colmap_reconstruction(
    frames_directory: Path,
    colmap_directory: Path,
    settings: ColmapSettings,
    *,
    workspace_directory: Path,
    execution_environment: CommandExecutionEnvironment,
    on_log: LogCallback | None = None,
) -> Path:
    """Run sparse automatic reconstruction and return the COLMAP workspace."""

    workspace_directory = workspace_directory.resolve()
    frames_directory = frames_directory.resolve()
    colmap_directory = colmap_directory.resolve()

    command = build_colmap_command(
        frames_directory,
        colmap_directory,
        settings,
        workspace_directory=workspace_directory,
    )

    if not frames_directory.is_dir():
        raise FileNotFoundError(f"Frames directory does not exist: {frames_directory}")
    if not any(frames_directory.glob("frame_*.jpg")):
        raise RuntimeError(
            f"Frames directory contains no JPEG frames: {frames_directory}"
        )

    colmap_directory.mkdir(parents=True, exist_ok=True)
    execution_environment.execute(
        command,
        workspace=workspace_directory,
        on_log=on_log,
    )

    sparse_model_directory = colmap_directory / "sparse" / "0"
    if not _looks_like_colmap_model(sparse_model_directory):
        raise RuntimeError(
            "COLMAP completed without producing a valid sparse/0 reconstruction"
        )

    return colmap_directory
