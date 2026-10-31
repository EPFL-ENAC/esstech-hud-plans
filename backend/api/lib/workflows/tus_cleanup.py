"""Cleanup of abandoned tus uploads from the tusd staging directory.

tusd's filestore performs no expiration cleanup, so a scheduled flow fails
abandoned uploads and their waiting reconstructions before removing expired
staging files and orphan binaries. Completed uploads are stored separately.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from prefect import flow, get_run_logger
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.concurrency import run_in_threadpool

from api.config import config
from api.db import get_engine
from api.lib.upload_storage import is_tus_upload_expired
from api.models.user import utc_now
from api.services.uploads import UserUploadsService


def remove_expired_uploads(
    upload_dir: Path,
    retention_days: int,
    *,
    now: datetime,
) -> list[str]:
    """Delete expired upload pairs and orphan binaries from the staging dir.

    Returns the names of the removed uploads. Only entries directly inside
    `upload_dir` are touched.
    """
    removed: list[str] = []

    if not upload_dir.is_dir():
        return removed

    candidates = {
        path.with_name(path.name.removesuffix(".info"))
        if path.name.endswith(".info")
        else path
        for path in upload_dir.iterdir()
    }
    for binary_path in sorted(candidates):
        if not is_tus_upload_expired(
            binary_path,
            now=now,
            retention_days=retention_days,
        ):
            continue
        try:
            binary_stat = binary_path.stat()
        except FileNotFoundError:
            binary_stat = None
        info_path = binary_path.with_name(binary_path.name + ".info")
        info_path.unlink(missing_ok=True)
        if binary_stat is not None:
            try:
                current_stat = binary_path.stat()
            except FileNotFoundError:
                current_stat = None
            if current_stat is not None and (
                current_stat.st_ino,
                current_stat.st_mtime,
            ) != (binary_stat.st_ino, binary_stat.st_mtime):
                continue
        binary_path.unlink(missing_ok=True)
        removed.append(binary_path.name)

    return removed


@flow(name="tus-cleanup")
async def tus_cleanup_flow() -> list[str]:
    run_logger = get_run_logger()
    now = utc_now()
    upload_dir = Path(config.TUSD_UPLOAD_DIR)
    if not upload_dir.is_dir():
        run_logger.warning("Upload staging directory is unavailable: %s", upload_dir)
        return []

    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        expired = await UserUploadsService(session).expire_abandoned_uploads(
            now=now,
            retention_days=config.TUSD_UPLOAD_RETENTION_DAYS,
        )
    for upload_id in expired:
        run_logger.info("Marked abandoned upload %s as failed", upload_id)

    removed = await run_in_threadpool(
        remove_expired_uploads,
        upload_dir,
        config.TUSD_UPLOAD_RETENTION_DAYS,
        now=now,
    )
    for name in removed:
        run_logger.info("Removed expired tus upload %s", name)
    return removed
