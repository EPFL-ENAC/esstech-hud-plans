import logging
import shutil
from pathlib import Path

from api.lib.utils.commands import LogCallback, run_logged_command
from api.models.workflows import ColmapSettings

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
COLMAP_COMMAND = BACKEND_ROOT / "external" / "bin" / "colmap"


def _resolve_colmap_command() -> str:
    if COLMAP_COMMAND.is_file():
        return str(COLMAP_COMMAND)

    system_colmap = shutil.which("colmap")
    if system_colmap is not None:
        return system_colmap

    raise FileNotFoundError("colmap executable was not found")


def build_colmap_command(
    frames_directory: Path,
    colmap_directory: Path,
    settings: ColmapSettings,
) -> list[str]:
    command = [
        _resolve_colmap_command(),
        "automatic_reconstructor",
        "--image_path",
        str(frames_directory),
        "--workspace_path",
        str(colmap_directory),
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
        command.extend(["--mapper", "global"])
    return command


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
    on_log: LogCallback | None = None,
) -> Path:
    """Run sparse automatic reconstruction and return the COLMAP workspace."""

    frames_directory = frames_directory.resolve()
    colmap_directory = colmap_directory.resolve()

    if not frames_directory.is_dir():
        raise FileNotFoundError(f"Frames directory does not exist: {frames_directory}")
    if not any(frames_directory.glob("frame_*.jpg")):
        raise RuntimeError(
            f"Frames directory contains no JPEG frames: {frames_directory}"
        )

    colmap_directory.mkdir(parents=True, exist_ok=True)
    command = build_colmap_command(frames_directory, colmap_directory, settings)

    run_logged_command(
        command,
        capture="combined",
        log_prefix="colmap",
        fallback_logger=logger,
        on_log=on_log,
    )

    sparse_model_directory = colmap_directory / "sparse" / "0"
    if not _looks_like_colmap_model(sparse_model_directory):
        raise RuntimeError(
            "COLMAP completed without producing a valid sparse/0 reconstruction"
        )

    return colmap_directory
