from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from api.config import config

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_ResultT = TypeVar("_ResultT")


def get_engine(db_url: str | None = None) -> AsyncEngine:
    """Return the process-wide async database engine."""

    global _engine
    if _engine is None:
        url = db_url or config.DB_URL
        kwargs: dict[str, object] = {"pool_pre_ping": True}
        if url.startswith("postgresql"):
            kwargs.update(
                pool_size=5,
                max_overflow=10,
                pool_recycle=1800,
                pool_use_lifo=True,
                pool_timeout=30,
            )
        _engine = create_async_engine(url, **kwargs)
    return _engine


async def retry_on_db_error(
    operation: Callable[[], Awaitable[_ResultT]],
    *,
    operation_name: str,
    max_retries: int = 10,
    retry_interval: float = 2.0,
) -> _ResultT:
    """Retry transient database connection failures."""

    last_exception: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await operation()
        except (OSError, OperationalError) as exc:
            last_exception = exc
            logger.warning(
                "%s attempt %d/%d failed: %s",
                operation_name,
                attempt + 1,
                max_retries,
                exc,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_interval)

    if last_exception is not None:
        raise last_exception
    raise RuntimeError(f"Failed {operation_name} after {max_retries} attempts")


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped SQLModel session."""

    async with AsyncSession(get_engine(), expire_on_commit=False) as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the async engine and its connection pool."""

    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
