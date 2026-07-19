from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestPasswordResetRequest:
    """Input DTO for POST /request-reset-email/ endpoint.

    Used to request a password reset email with optional redirect URL.
    """
    email: str
    redirect_url: str | None = None
