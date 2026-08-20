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


def second_factor_required(
    *,
    two_factor_enabled: bool,
    has_confirmed_totp_device: bool,
    has_static_device: bool,
) -> bool:
    """THE rule for "does this credential check still owe a second factor?".

    Deliberately stated once, over plain facts rather than an entity, so every
    door into the product can ask it: the password login, magic-link sign-in,
    and Google sign-in. It used to live inline in ``LoginUseCase`` alone, which
    is exactly why the passwordless paths walked past it and handed TOTP-armed
    accounts a full session.

    The device clause is not decoration. A flag with no device behind it would
    raise a challenge nothing can answer — a lockout, not a control — so an
    armed flag only enforces once there is a confirmed TOTP device or a set of
    recovery codes to satisfy it.
    """
    if not two_factor_enabled:
        return False
    return has_confirmed_totp_device or has_static_device
