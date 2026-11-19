from unittest.mock import AsyncMock

import pytest

from api.services.idempotency import IdempotencyService


@pytest.fixture
def sqlite_idempotency_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise real transactions on SQLite; test advisory locks on PostgreSQL."""

    monkeypatch.setattr(IdempotencyService, "_try_lock", AsyncMock(return_value=True))
