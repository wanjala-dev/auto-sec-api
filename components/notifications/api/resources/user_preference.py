"""Resource DTOs for user notification preference endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserPreferenceResource:
    """Output DTO for user preference detail endpoints."""
    id: int
    user: int
    darkmode: str
    language: str | None = None
    email_notifications: bool = False
    push_notifications: bool = False
    notifications_enabled: bool = True


@dataclass(frozen=True)
class UserPreferenceCollectionResource:
    """Output DTO for user preference list endpoint."""
    items: list[UserPreferenceResource]
    count: int = 0
