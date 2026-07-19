"""Domain policy for OTP / two-factor verification.

Pure business rules — no Django, no ORM.
"""

from __future__ import annotations

from components.identity.domain.entities.user_entity import UserEntity


def requires_otp(user: UserEntity) -> bool:
    """Return True if this user must pass OTP verification to complete auth."""
    return user.two_factor_enabled


def otp_bypass_allowed(user: UserEntity) -> bool:
    """Return True if OTP can be bypassed (2FA not enabled)."""
    return not user.two_factor_enabled
