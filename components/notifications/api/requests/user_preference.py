"""Request DTOs for user notification preference endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateUserPreferenceRequest:
    """Input DTO for POST /userpreferences/ endpoint."""
    user: int
    darkmode: str | None = None
    language: str | None = None
    email_notifications: bool = False
    push_notifications: bool = False
    notifications_enabled: bool = True


@dataclass(frozen=True)
class UpdateUserPreferenceRequest:
    """Input DTO for PATCH /userpreferences/<uuid>/ endpoint."""
    darkmode: str | None = None
    language: str | None = None
    email_notifications: bool | None = None
    push_notifications: bool | None = None
    notifications_enabled: bool | None = None
