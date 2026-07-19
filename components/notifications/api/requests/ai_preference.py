"""Request DTOs for AI notification preference endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CreateAINotificationPreferenceRequest:
    """Input DTO for POST /preferences/ai/ endpoint."""
    workspace: str
    channel: str
    is_enabled: bool = True


@dataclass(frozen=True)
class UpdateAINotificationPreferenceRequest:
    """Input DTO for PATCH /preferences/ai/<workspace_id>/ endpoint."""
    channel: str | None = None
    is_enabled: bool | None = None
