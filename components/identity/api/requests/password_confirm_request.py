from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class PasswordConfirmRequest:
    """Input DTO for POST /otp/static/create/ and /otp/delete/ endpoints.

    Used to confirm password for sensitive OTP operations.
    """
    password: str
