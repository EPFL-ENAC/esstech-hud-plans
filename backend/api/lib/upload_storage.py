"""Filesystem operations for completed uploads and reconstruction inputs."""

import os
import shutil
from pathlib import Path
from uuid import UUID

from api.config import config
from api.lib.tus import tus_file_path


def upload_file_path(upload_id: UUID, filename: str) -> Path:
    extension = Path(filename).suffix.lower()
    return config.DATA_PATH / "uploads" / upload_id.hex / f"input{extension}"


def validate_completed_file(path: Path, expected_size: int) -> None:
    if expected_size <= 0 or not path.is_file() or path.stat().st_size != expected_size:
        raise OSError("Completed upload is missing or incomplete")


def copy_completed_file(
    source: Path,
    destination: Path,
    expected_size: int,
) -> None:
    """Publish a complete copy atomically; reuse a previous successful copy."""

    if destination.exists():
        validate_completed_file(destination, expected_size)
        return

    validate_completed_file(source, expected_size)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        shutil.copyfile(source, temporary)
        validate_completed_file(temporary, expected_size)
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def remove_tus_files(upload_id: UUID) -> None:
    source = Path(tus_file_path(upload_id))
    source.unlink(missing_ok=True)
    source.with_name(source.name + ".info").unlink(missing_ok=True)
