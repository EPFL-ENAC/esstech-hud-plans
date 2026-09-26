"""Scheduled cleanup of expired chunked upload sessions."""

import logging
from datetime import timedelta

from api.db import get_engine
from api.models.user import utc_now
from api.services.uploads import ORPHAN_TEMP_GRACE_SECONDS, UploadService
from prefect import flow, get_run_logger
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


@flow(name="purge-expired-upload-sessions")
async def purge_expired_upload_sessions() -> None:
    run_logger = get_run_logger()
    now = utc_now()

    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        uploads = UploadService(session)
        expired = await uploads.delete_expired_sessions(now=now)
        finalized = await uploads.delete_finalized_sessions(
            older_than=now - timedelta(seconds=ORPHAN_TEMP_GRACE_SECONDS)
        )
        orphans = await uploads.delete_orphan_temp_dirs()

    run_logger.info(
        "Upload cleanup removed %d expired sessions, %d stale finalized "
        "sessions, and %d orphaned staging dirs",
        expired,
        finalized,
        orphans,
    )
