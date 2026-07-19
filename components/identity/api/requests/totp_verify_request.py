from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class TOTPVerifyRequest:
    """Input DTO for POST /otp/verify/ endpoint.

    Used to verify a TOTP token to enable two-factor authentication.
    """
    token: str
