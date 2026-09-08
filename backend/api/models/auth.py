from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AuthenticatedUser:
    """Identity and authorization claims from a verified Keycloak token."""

    sub: str
    username: str | None = None
    email: str | None = None
    name: str | None = None
    roles: list[str] = field(default_factory=list)
    client_roles: list[str] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        """True when the user holds the internal "admin" client role.

        Matches the frontend gate (src/lib/auth.ts isAdmin), which checks the
        Keycloak client role "admin" rather than a realm role.
        """

        return "admin" in self.client_roles
