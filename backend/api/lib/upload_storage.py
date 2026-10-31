"""Filesystem operations for completed uploads and reconstruction inputs."""

import os
import shutil
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from api.config import config
from api.lib.tus import tus_file_path

# Keep binaries without metadata for a day in case tusd crashed during a write.
ORPHAN_BINARY_RETENTION_SECONDS = 24 * 60 * 60


def is_tus_upload_expired(
    upload_path: Path,
    *,
    now: datetime,
    retention_days: int,
    created_at: datetime | None = None,
) -> bool:
    """Check staging activity without treating filesystem errors as missing files."""

    info_path = upload_path.with_name(upload_path.name + ".info")
    try:
        info_stat = info_path.stat()
    except FileNotFoundError:
        info_stat = None
    try:
        binary_stat = upload_path.stat()
    except FileNotFoundError:
        binary_stat = None

    timestamp = now.timestamp()
    retention_seconds = timedelta(days=retention_days).total_seconds()
    if info_stat is not None:
        if not stat.S_ISREG(info_stat.st_mode):
            return False
        if timestamp - info_stat.st_mtime <= retention_seconds:
            return False
        if binary_stat is None:
            return True
        return (
            stat.S_ISREG(binary_stat.st_mode)
            and timestamp - binary_stat.st_mtime > ORPHAN_BINARY_RETENTION_SECONDS
        )
    if binary_stat is not None:
        return (
            stat.S_ISREG(binary_stat.st_mode)
            and timestamp - binary_stat.st_mtime > ORPHAN_BINARY_RETENTION_SECONDS
        )
    if created_at is None:
        return False
    # Database timestamps without an offset represent UTC.
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return timestamp - created_at.timestamp() > retention_seconds


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
