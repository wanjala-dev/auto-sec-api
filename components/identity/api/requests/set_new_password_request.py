from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class SetNewPasswordRequest:
    """Input DTO for PATCH /password-reset-complete/ endpoint.

    Used to set a new password after password reset validation.
    """
    password: str
    token: str
    uidb64: str
