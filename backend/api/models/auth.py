from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identity claims from a verified Keycloak token."""

    sub: str
    username: str | None = None
    email: str | None = None
    name: str | None = None
