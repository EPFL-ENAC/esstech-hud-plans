"""Filesystem helpers for chunked video upload staging."""

from pathlib import Path
from uuid import UUID

from api.config import config


def upload_root() -> Path:
    """Root directory holding one staging directory per upload session."""

    return config.UPLOAD_ROOT_PATH


def session_dir(session_id: UUID) -> Path:
    """Staging directory path of one upload session, without creating it."""

    return upload_root() / session_id.hex


def make_session_temp_dir(session_id: UUID) -> Path:
    """Create and return the staging directory of one upload session."""

    directory = session_dir(session_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def part_file(session_id: UUID, chunk_index: int) -> Path:
    """Path of the stored part file for one chunk of an upload session."""

    return session_dir(session_id) / f"{chunk_index}.part"
