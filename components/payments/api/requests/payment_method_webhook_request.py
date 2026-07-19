"""Request DTO for payment method webhook endpoint."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaymentMethodWebhookRequest:
    """Input DTO for webhook upsert request."""
    name: str | None = None
    url: str | None = None
    status: str | None = None
    signing_secret: str | None = None
    secret: str | None = None
