from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class StaticVerifyRequest:
    """Input DTO for POST /otp/static/verify/ endpoint.

    Used to verify a static recovery code for two-factor authentication.
    """
    token: str
