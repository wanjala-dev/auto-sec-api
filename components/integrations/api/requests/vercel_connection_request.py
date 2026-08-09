"""Request DTOs: create / update a VercelConnection (ADR 0021 D2)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Statuses a workspace may set via the API. ``error`` is system-owned (set by verify);
# ``connected`` re-enables, ``disabled`` pauses a connection.
_VALID_STATUSES = {"connected", "disabled"}

# API-boundary shape check for the team the operator types. Intentionally mirrors
# ``components.cloud_posture.domain.scan_targets.validate_vercel_scan_target`` — two
# regexes at two trust boundaries (this form input vs. the scan-time argv/env gate),
# the same defense-in-depth split the AWS account id has (request DTO vs.
# ``validate_aws_scan_target``). Keep them in sync.
_TEAM_ID_RE = re.compile(r"^team_[A-Za-z0-9]{1,64}$")
_TEAM_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _split_team(raw: str) -> tuple[str, str] | None:
    """Classify the typed team as (team_id, team_slug); ``None`` when malformed."""
    team = (raw or "").strip()
    if _TEAM_ID_RE.match(team):
        return team, ""
    if _TEAM_SLUG_RE.match(team):
        return "", team
    return None


@dataclass(frozen=True)
class CreateVercelConnectionRequest:
    """Validated input for ``POST /integrations/workspaces/<ws>/vercel-connections/``.

    ``team`` is REQUIRED: the connection names the ONE team it consents to scan
    (ADR 0021 D3 — an unpinned token would let Prowler scan every team the token's
    user belongs to). The token ask is documented in the panel: minted from a
    Viewer-role seat, scoped to this team, with an expiration.
    """

    team: str
    token: str
    name: str = ""

    @classmethod
    def from_payload(cls, data: dict) -> CreateVercelConnectionRequest:
        data = data or {}
        return cls(
            team=str(data.get("team") or "").strip(),
            token=str(data.get("token") or "").strip(),
            name=str(data.get("name") or "").strip(),
        )

    def validation_error(self) -> str | None:
        if not self.team:
            return "A team id or slug is required — a Vercel connection names the one team it may scan."
        if _split_team(self.team) is None:
            return "team must be a Vercel team id (team_…) or a lowercase team slug."
        if not self.token:
            return "A Vercel API token is required (create it from a Viewer-role seat, scoped to this team)."
        return None

    @property
    def team_parts(self) -> tuple[str, str]:
        """``(team_id, team_slug)`` — exactly one is non-empty after validation."""
        return _split_team(self.team) or ("", "")


@dataclass(frozen=True)
class UpdateVercelConnectionRequest:
    """Partial update — only supplied fields are applied. ``None`` means 'leave as-is'."""

    name: str | None = None
    team: str | None = None
    status: str | None = None
    token: str | None = None

    @classmethod
    def from_payload(cls, data: dict) -> UpdateVercelConnectionRequest:
        data = data or {}
        name = data.get("name")
        team = data.get("team")
        status = data.get("status")
        token = data.get("token")
        return cls(
            name=None if name is None else str(name).strip(),
            team=None if team is None else str(team).strip(),
            status=None if status is None else str(status).strip().lower(),
            token=None if token is None else str(token).strip(),
        )

    def validation_error(self) -> str | None:
        if self.status is not None and self.status not in _VALID_STATUSES:
            return "status can only be set to 'connected' or 'disabled' via the API."
        if self.team is not None:
            if not self.team:
                return "team cannot be cleared — a Vercel connection must name one team."
            if _split_team(self.team) is None:
                return "team must be a Vercel team id (team_…) or a lowercase team slug."
        return None

    @property
    def team_parts(self) -> tuple[str, str] | None:
        """``(team_id, team_slug)`` when a team was supplied, else ``None``."""
        if self.team is None:
            return None
        return _split_team(self.team) or ("", "")
