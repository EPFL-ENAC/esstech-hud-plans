from typing import Any

import requests
from api.config import config
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class TokenRequest(BaseModel):
    """Authorization code returned by the Keycloak login page."""

    code: str
    redirect_uri: str


class TokenResponse(BaseModel):
    """Access token issued by Keycloak after a successful exchange."""

    access_token: str
    token_type: str
    expires_in: int


def _token_url() -> str:
    return f"{config.KEYCLOAK_ENDPOINT}/realms/{config.KEYCLOAK_REALM}/protocol/openid-connect/token"


def _redirect_uri() -> str:
    """Redirect URI expected from the frontend, derived from APP_URL.

    This must match the frontend construction in src/boot/api.ts:
    `${window.location.origin}${window.location.pathname}#/callback`.
    """

    return f"{config.APP_URL.rstrip('/')}/#/callback"


@router.post("/token", response_model=TokenResponse)
def exchange_code(req: TokenRequest) -> TokenResponse:
    """Exchange the authorization code for an access token.

    The exchange is performed server-side so that the client secret never
    reaches the browser. Returns the access token to be stored by the client.

    Defined as a plain (sync) function so FastAPI runs it in a worker
    threadpool. The requests.post call against Keycloak is blocking and must
    not run on the event loop.
    """

    expected_redirect_uri = _redirect_uri()
    if req.redirect_uri != expected_redirect_uri:
        raise HTTPException(
            status_code=400,
            detail="Redirect URI does not match the expected value",
        )

    data = {
        "grant_type": "authorization_code",
        "client_id": config.KEYCLOAK_CLIENT_ID,
        "client_secret": config.KEYCLOAK_CLIENT_SECRET,
        "code": req.code,
        "redirect_uri": req.redirect_uri,
    }

    try:
        response = requests.post(_token_url(), data=data, timeout=15)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=400,
            detail="Token exchange with Keycloak failed",
        ) from exc

    payload: dict[str, Any] = response.json()
    return TokenResponse(
        access_token=payload["access_token"],
        token_type=payload.get("token_type", "bearer"),
        expires_in=int(payload.get("expires_in", 0)),
    )
