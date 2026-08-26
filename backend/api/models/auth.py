from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class User:
    """Authenticated user parsed from a Keycloak access token."""

    sub: str = ""
    username: str = ""
    email: str = ""
    name: str = ""
    roles: list[str] = field(default_factory=list)
    client_roles: list[str] = field(default_factory=list)

    @property
    def is_admin(self) -> bool:
        """True when the user holds the internal "admin" client role.

        Matches the frontend gate (src/lib/auth.ts isAdmin), which checks the
        Keycloak client role "admin" rather than a realm role.
        """

        return "admin" in self.client_roles
