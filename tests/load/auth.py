"""JWT auth helpers for load tests.

Single helper used by every authenticated scenario. Logs in once, caches the
access + refresh tokens, refreshes proactively when the access token has less
than `LOAD_ACCESS_TOKEN_REFRESH_BUFFER_S` seconds of life.

Never bake an access token into env vars. Always login → cache → refresh.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from locust import HttpUser

logger = logging.getLogger(__name__)


class LoginFailed(RuntimeError):
    """Raised when login does not return tokens (e.g. 2FA required, bad creds)."""


@dataclass
class Tokens:
    access: str
    refresh: str
    access_expiry_epoch_s: float

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> "Tokens":
        tokens = payload.get("tokens") or payload
        access = tokens.get("access")
        refresh = tokens.get("refresh")
        if not access or not refresh:
            raise LoginFailed(
                f"login response missing tokens; otp_required={payload.get('otp_required')}"
            )
        return cls(
            access=access,
            refresh=refresh,
            access_expiry_epoch_s=_decode_jwt_exp(access),
        )


def _decode_jwt_exp(token: str) -> float:
    """Decode the `exp` claim from a JWT without verification (we trust our own server)."""
    try:
        _, payload_b64, _ = token.split(".")
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        return float(payload.get("exp", time.time() + 300))
    except (ValueError, KeyError, json.JSONDecodeError):
        return time.time() + 300


def login(client: HttpUser.client, email: str, password: str) -> Tokens:
    """POST /identity/login/ → Tokens. Raises LoginFailed if 2FA blocks the login."""
    response = client.post(
        "/identity/login/",
        json={"email": email, "password": password},
        name="/identity/login/",
        catch_response=True,
    )
    with response:
        if response.status_code != 200:
            response.failure(f"login {response.status_code}: {response.text[:200]}")
            raise LoginFailed(f"login returned {response.status_code}")
        try:
            return Tokens.from_response(response.json())
        except LoginFailed:
            response.failure("login response missing tokens (likely otp_required)")
            raise
        finally:
            response.success()


def refresh(client: HttpUser.client, refresh_token: str) -> Tokens:
    """POST /identity/token/refresh/ → new Tokens."""
    response = client.post(
        "/identity/token/refresh/",
        json={"refresh": refresh_token},
        name="/identity/token/refresh/",
        catch_response=True,
    )
    with response:
        if response.status_code != 200:
            response.failure(f"refresh {response.status_code}")
            raise LoginFailed(f"refresh returned {response.status_code}")
        payload = response.json()
        new_access = payload.get("access")
        new_refresh = payload.get("refresh", refresh_token)
        if not new_access:
            response.failure("refresh response missing access token")
            raise LoginFailed("refresh response missing access token")
        response.success()
        return Tokens(
            access=new_access,
            refresh=new_refresh,
            access_expiry_epoch_s=_decode_jwt_exp(new_access),
        )


def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}
