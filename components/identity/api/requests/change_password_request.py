from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ChangePasswordRequest:
    """Input DTO for PATCH /changepassword/ endpoint.

    Used to change the authenticated user's password.
    """
    old_password: str
    new_password: str
    confirm_password: str
