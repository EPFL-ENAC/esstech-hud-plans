from __future__ import annotations

from typing import Any

import jwt
from api.config import config
from api.models.auth import User
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

_jwks_client: jwt.PyJWKClient | None = None


def _keycloak_base() -> str:
    """Base URL of the configured Keycloak realm."""

    return f"{config.KEYCLOAK_ENDPOINT}/realms/{config.KEYCLOAK_REALM}"


def _get_jwks_client() -> jwt.PyJWKClient:
    """Return a cached PyJWKClient bound to the Keycloak JSON Web Key Set."""

    global _jwks_client
    if _jwks_client is None:
        certs_url = f"{_keycloak_base()}/protocol/openid-connect/certs"
        _jwks_client = jwt.PyJWKClient(certs_url)
    return _jwks_client


def _parse_user(payload: dict[str, Any]) -> User:
    """Build a User from the claims of a verified Keycloak token."""

    realm_access = payload.get("realm_access") or {}
    roles = list(realm_access.get("roles") or [])
    # Client roles are read from resource_access[<client_id>].roles so that
    # "admin" means the same thing here as in the frontend gate.
    resource_access = payload.get("resource_access") or {}
    client_entry = resource_access.get(config.KEYCLOAK_CLIENT_ID) or {}
    client_roles = list(client_entry.get("roles") or [])
    return User(
        sub=str(payload.get("sub", "")),
        username=str(payload.get("preferred_username", "")),
        email=str(payload.get("email", "")),
        name=str(payload.get("name", "")),
        roles=roles,
        client_roles=client_roles,
    )


def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """Resolve the authenticated user from the bearer token.

    Verifies the JWT signature against the Keycloak JWKS and parses the
    identity and roles from the token claims. Raises 401 when the token is
    missing or invalid.
    """

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = credentials.credentials
    try:
        key = _get_jwks_client().get_signing_key_from_jwt(token)
        # Verify signature, issuer and expiry via PyJWT; we check the audience
        # manually below so we accept the token if it is addressed to this
        # client (aud) or issued on behalf of it (azp).
        payload = jwt.decode(
            token,
            key.key,
            algorithms=[key.algorithm_name],
            issuer=_keycloak_base(),
            options={"verify_aud": False},
        )

        aud = payload.get("aud")
        audiences = set(aud) if isinstance(aud, list) else ({aud} if aud else set())
        azp = payload.get("azp")
        if (
            config.KEYCLOAK_CLIENT_ID not in audiences
            and azp != config.KEYCLOAK_CLIENT_ID
        ):
            raise jwt.InvalidAudienceError("Audience doesn't match")
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    return _parse_user(payload)


def require_admin(
    current_user: User = Depends(require_user),
) -> User:
    """Resolve the authenticated user and require the admin role.

    Raises 403 when the user does not hold the \"admin\" realm role.
    """

    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user
