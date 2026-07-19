"""Output DTOs for invitation endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InvitationAcceptanceResource:
    """Output DTO for invitation acceptance response."""

    success: bool
    team_id: int | None = None
    joined_at: str | None = None


@dataclass(frozen=True)
class PendingInvitationResource:
    """Output DTO for pending invitation list."""

    email: str
    latest_sent: str | None = None
    teams: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class InvitationBatchResultResource:
    """Output DTO for batch invitation result."""

    success: bool
    message: str
    results: dict | None = None
