"""Cleanup of abandoned tus uploads from the tusd staging directory.

tusd's filestore performs no expiration cleanup, so a scheduled flow removes
uploads that were never finished or never picked up by a submission.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from prefect import flow, get_run_logger

from api.config import config

logger = logging.getLogger(__name__)

# Binaries without an .info file can never be resumed; keep them for a day so
# a crash during tusd state writes does not discard live uploads.
ORPHAN_BINARY_RETENTION_SECONDS = 24 * 60 * 60
SECONDS_PER_DAY = 24 * 60 * 60


def remove_expired_uploads(upload_dir: Path, retention_days: int) -> list[str]:
    """Delete expired upload pairs and orphan binaries from the staging dir.

    Returns the names of the removed uploads. Only entries directly inside
    `upload_dir` are touched.
    """

    now = time.time()
    retention_seconds = retention_days * SECONDS_PER_DAY
    removed: list[str] = []

    if not upload_dir.is_dir():
        return removed

    for info_path in upload_dir.glob("*.info"):
        binary_path = info_path.with_name(info_path.name.removesuffix(".info"))
        try:
            age = now - info_path.stat().st_mtime
        except OSError:
            continue
        if age <= retention_seconds:
            continue
        if not info_path.is_file():
            continue
        info_path.unlink(missing_ok=True)
        binary_path.unlink(missing_ok=True)
        removed.append(binary_path.name)

    for binary_path in upload_dir.iterdir():
        if binary_path.name.endswith(".info") or not binary_path.is_file():
            continue
        info_path = binary_path.with_name(binary_path.name + ".info")
        if info_path.exists():
            continue
        try:
            age = now - binary_path.stat().st_mtime
        except OSError:
            continue
        if age <= ORPHAN_BINARY_RETENTION_SECONDS:
            continue
        binary_path.unlink(missing_ok=True)
        removed.append(binary_path.name)

    return removed


@flow(name="tus-cleanup")
def tus_cleanup_flow() -> list[str]:
    run_logger = get_run_logger()
    removed = remove_expired_uploads(
        Path(config.TUSD_UPLOAD_DIR),
        config.TUSD_UPLOAD_RETENTION_DAYS,
    )
    for name in removed:
        run_logger.info("Removed expired tus upload %s", name)
    return removed
