"""Request DTO for Stripe Connect callback."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StripeConnectCallbackRequest:
    """Input DTO for Stripe Connect callback request."""
    method_id: str | None = None
    state: str | None = None
    result: str | None = None
    error: str | None = None
    error_code: str | None = None
    error_description: str | None = None
    account: str | None = None
    account_id: str | None = None
