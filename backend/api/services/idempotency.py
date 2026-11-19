from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.models.idempotency import IdempotencyRecords, IdempotencyStatus


class IdempotencyInProgressError(Exception):
    """Another transaction is accepting the same operation."""


class IdempotencyService:
    """Commit an operation's database writes and completion record atomically."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _try_lock(self, owner_id: UUID, idempotency_key: str) -> bool:
        # PostgreSQL advisory locks take a signed bigint. Python's hash() is
        # process-dependent, so use a stable digest shared by all API workers.
        digest = sha256(f"{owner_id}:{idempotency_key}".encode()).digest()
        lock_id = int.from_bytes(digest[:8], byteorder="big", signed=True)
        return bool(
            await self._session.scalar(select(func.pg_try_advisory_xact_lock(lock_id)))
        )

    @asynccontextmanager
    async def operation(
        self,
        *,
        owner_id: UUID,
        idempotency_key: str,
    ) -> AsyncIterator[bool]:
        """Own the acceptance transaction; yield whether to perform work.

        The caller and its services must use this session without committing
        inside the context. External side effects belong after the context.
        """

        try:
            if not await self._try_lock(owner_id, idempotency_key):
                raise IdempotencyInProgressError

            record = await self._session.get(
                IdempotencyRecords, (owner_id, idempotency_key)
            )
            if record is not None and record.status == IdempotencyStatus.COMPLETED:
                yield False
            else:
                if record is None:
                    record = IdempotencyRecords(
                        owner_id=owner_id,
                        idempotency_key=idempotency_key,
                    )
                    self._session.add(record)
                await self._session.flush()
                yield True
                record.status = IdempotencyStatus.COMPLETED

            await self._session.commit()
        except BaseException:
            await self._session.rollback()
            raise
