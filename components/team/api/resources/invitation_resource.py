"""Output DTOs for invitation endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InvitationResource:
    """Output DTO for invitation detail."""
    id: int | None = None
    team: str | int | None = None
    email: str | None = None
    code: str | None = None
    status: str | None = None
    date_sent: str | None = None
    accepted_at: str | None = None


@dataclass(frozen=True)
class PendingInvitationResource:
    """Output DTO for pending invitation list endpoints (GET /api/teams/invitations/)."""
    email: str | None = None
    latest_sent: str | None = None
    teams: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class PendingInvitationCollectionResource:
    """Output DTO for pending invitation list endpoints."""
    items: list[PendingInvitationResource]
    count: int = 0
    results: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class InvitationAcceptanceResource:
    """Output DTO for invitation acceptance response (POST /api/teams/invite/accept/)."""
    success: bool | None = None
    team_id: int | None = None
    joined_at: str | None = None
