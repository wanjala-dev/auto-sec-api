"""VercelApiAdapter — the ``VercelApiPort`` implementation over api.vercel.com (ADR 0021 D2).

Bearer-token probes only (the exact calls Prowler validates with, ADR 0021 R3):
``GET /v2/user`` for token validity, ``GET /v2/teams/{idOrSlug}`` for team access,
and best-effort ``GET /v5/user/tokens/current`` for the token's own expiry. The
token is NEVER logged and never appears in a detail string; failures map to
operator-safe reasons. Env-var VALUES are never read anywhere in this integration
(ADR 0021 D2 env-var scope discipline).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import requests
from django.views.decorators.debug import sensitive_variables

from components.integrations.application.ports.vercel_api_port import (
    VercelApiPort,
    VercelHealth,
    VercelTeam,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.vercel.com"
_TIMEOUT_SECONDS = 15

# Operator-safe reasons per status code — the 401/403/429 trio Prowler documents.
_STATUS_REASONS = {
    401: "The Vercel API token is invalid, revoked, or expired.",
    403: "The Vercel API token does not have access (insufficient permissions or a disabled integration).",
    404: "Not found — check the team id/slug.",
    429: "Vercel rate-limited the request — try again shortly.",
}


class VercelApiAdapter(VercelApiPort):
    def __init__(self, token: str, *, base_url: str = _BASE_URL):
        self._token = token
        self._base_url = base_url.rstrip("/")

    @sensitive_variables("_token")
    def _get(self, path: str) -> requests.Response:
        return requests.get(
            f"{self._base_url}{path}",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=_TIMEOUT_SECONDS,
        )

    def verify_token(self) -> VercelHealth:
        try:
            response = self._get("/v2/user")
        except requests.RequestException:
            logger.exception("vercel_verify_token_unreachable")
            return VercelHealth(ok=False, detail="api.vercel.com is not reachable.")
        if response.status_code == 200:
            return VercelHealth(ok=True)
        return VercelHealth(ok=False, detail=_reason(response.status_code))

    def get_team(self, team: str) -> tuple[VercelHealth, VercelTeam | None]:
        # The caller has already validated the team's shape (the scan-target gate);
        # it is safe to interpolate into the path.
        try:
            response = self._get(f"/v2/teams/{team}")
        except requests.RequestException:
            logger.exception("vercel_get_team_unreachable")
            return VercelHealth(ok=False, detail="api.vercel.com is not reachable."), None
        if response.status_code != 200:
            return VercelHealth(ok=False, detail=_reason(response.status_code)), None
        try:
            data = response.json() or {}
        except ValueError:
            return VercelHealth(ok=False, detail="Vercel returned an unreadable team payload."), None
        team_id = str(data.get("id") or "")
        if not team_id:
            return VercelHealth(ok=False, detail="Vercel returned a team without an id."), None
        return VercelHealth(ok=True), VercelTeam(
            id=team_id,
            slug=str(data.get("slug") or ""),
            name=str(data.get("name") or ""),
        )

    def get_token_expiry(self) -> datetime | None:
        try:
            response = self._get("/v5/user/tokens/current")
            if response.status_code != 200:
                return None
            payload = (response.json() or {}).get("token") or {}
            expires_ms = payload.get("expiresAt")
            if not expires_ms:
                return None  # "No expiration" tokens have none — nothing to nag about
            return datetime.fromtimestamp(int(expires_ms) / 1000, tz=UTC)
        except (requests.RequestException, ValueError, TypeError, OSError):
            # Best-effort by contract — expiry display is a nicety, never a gate.
            logger.info("vercel_token_expiry_unavailable")
            return None


def _reason(status_code: int) -> str:
    return _STATUS_REASONS.get(status_code, f"Vercel API returned HTTP {status_code}.")
