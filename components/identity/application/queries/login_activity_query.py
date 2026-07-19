"""Read DTO for the self-serve login-activity list."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class LoginActivityQuery:
    """Filters for a user's own auth-audit event feed.

    ``created_from`` / ``created_to`` are inclusive datetime bounds already
    parsed by the controller (requests parsing stays at the HTTP edge).
    """

    user_id: UUID
    event_code: str | None = None
    success: bool | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
