import asyncio
from types import SimpleNamespace

import jwt
import pytest
from api.models.auth import AuthenticatedUser
from api.models.user import User
from api.services import auth
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import OperationalError


def test_authenticate_user_parses_and_normalizes_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signing_key = SimpleNamespace(
        key="public-key",
        algorithm_name="RS256",
    )
    jwks_client = SimpleNamespace(get_signing_key_from_jwt=lambda token: signing_key)
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: jwks_client)
    monkeypatch.setattr(
        auth.jwt,
        "decode",
        lambda *args, **kwargs: {
            "sub": " subject-1 ",
            "preferred_username": " user ",
            "email": "",
            "name": None,
            "aud": auth.config.KEYCLOAK_CLIENT_ID,
            "realm_access": {"roles": ["realm-role"]},
            "resource_access": {auth.config.KEYCLOAK_CLIENT_ID: {"roles": ["admin"]}},
        },
    )

    identity = auth.authenticate_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
    )

    assert identity == AuthenticatedUser(
        sub="subject-1",
        username="user",
        email=None,
        name=None,
        roles=["realm-role"],
        client_roles=["admin"],
    )


def test_authenticate_user_rejects_missing_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signing_key = SimpleNamespace(key="public-key", algorithm_name="RS256")
    jwks_client = SimpleNamespace(get_signing_key_from_jwt=lambda token: signing_key)
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: jwks_client)
    monkeypatch.setattr(
        auth.jwt,
        "decode",
        lambda *args, **kwargs: {"azp": auth.config.KEYCLOAK_CLIENT_ID},
    )

    with pytest.raises(HTTPException) as exc_info:
        auth.authenticate_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")
        )

    assert exc_info.value.status_code == 401


def test_parse_authenticated_user_rejects_missing_subject() -> None:
    with pytest.raises(jwt.InvalidTokenError):
        auth._parse_authenticated_user({})


def test_require_user_maps_database_errors_to_service_unavailable() -> None:
    class FailingUserService:
        async def sync_authenticated_user(self, identity: AuthenticatedUser) -> User:
            raise OperationalError("SELECT", {}, RuntimeError("offline"))

    async def run() -> None:
        with pytest.raises(HTTPException) as exc_info:
            await auth.require_user(
                AuthenticatedUser(sub="subject-1"),
                FailingUserService(),  # type: ignore[arg-type]
            )
        assert exc_info.value.status_code == 503

    asyncio.run(run())


def test_require_admin_uses_current_token_roles() -> None:
    user = User(keycloak_sub="subject-1")

    async def run() -> None:
        assert (
            await auth.require_admin(
                user,
                AuthenticatedUser(sub="subject-1", client_roles=["admin"]),
            )
            is user
        )

        with pytest.raises(HTTPException) as exc_info:
            await auth.require_admin(user, AuthenticatedUser(sub="subject-1"))
        assert exc_info.value.status_code == 403

    asyncio.run(run())
