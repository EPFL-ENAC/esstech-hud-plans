from __future__ import annotations

import logging
from typing import Annotated, Any

import jwt
from api.config import config
from api.db import get_session
from api.models.auth import AuthenticatedUser
from api.models.user import User
from api.services.users import UserService
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

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


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _parse_authenticated_user(payload: dict[str, Any]) -> AuthenticatedUser:
    """Build an authenticated identity from verified Keycloak claims."""

    sub = _optional_string(payload.get("sub"))
    if sub is None:
        raise jwt.InvalidTokenError("Token is missing its subject")

    realm_access = payload.get("realm_access") or {}
    roles = list(realm_access.get("roles") or [])
    # Client roles are read from resource_access[<client_id>].roles so that
    # "admin" means the same thing here as in the frontend gate.
    resource_access = payload.get("resource_access") or {}
    client_entry = resource_access.get(config.KEYCLOAK_CLIENT_ID) or {}
    client_roles = list(client_entry.get("roles") or [])
    return AuthenticatedUser(
        sub=sub,
        username=_optional_string(payload.get("preferred_username")),
        email=_optional_string(payload.get("email")),
        name=_optional_string(payload.get("name")),
        roles=roles,
        client_roles=client_roles,
    )


def authenticate_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthenticatedUser:
    """Validate a bearer token and return its authenticated identity.

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
        return _parse_authenticated_user(payload)
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc


def get_user_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserService:
    """Build a request-scoped user service."""

    return UserService(session)


async def require_user(
    identity: Annotated[AuthenticatedUser, Depends(authenticate_user)],
    users: Annotated[UserService, Depends(get_user_service)],
) -> User:
    """Resolve a verified identity to its persisted application user."""

    try:
        return await users.sync_authenticated_user(identity)
    except (OSError, SQLAlchemyError) as exc:
        logger.exception("Failed to synchronize authenticated user")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="User database is unavailable",
        ) from exc


async def require_admin(
    current_user: User = Depends(require_user),
    identity: AuthenticatedUser = Depends(authenticate_user),
) -> User:
    """Resolve the authenticated user and require the admin role.

    Raises 403 when the user does not hold the \"admin\" client role.
    """

    if not identity.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user
