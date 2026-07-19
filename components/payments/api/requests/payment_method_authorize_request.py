"""Request DTO for payment method authorization endpoint."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaymentMethodAuthorizeRequest:
    """Input DTO for payment method authorization request."""
    redirect_url: str | None = None
    refresh_url: str | None = None
