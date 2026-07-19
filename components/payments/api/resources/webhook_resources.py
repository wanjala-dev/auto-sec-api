"""Output DTOs for webhook endpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebhookEventResource:
    """Output DTO for webhook event data."""
    id: str | None = None
    type: str | None = None
    created: int | None = None
    data: dict | None = None
    livemode: bool | None = None
    object: str | None = None


@dataclass(frozen=True)
class WebhookResponseResource:
    """Output DTO for webhook response."""
    status: str | None = None
    message: str | None = None
    event_id: str | None = None
    duplicate: bool | None = None
