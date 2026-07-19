"""DRF throttle classes for identity endpoints.

Combines authentication throttles (login, password reset, email verify) and
OTP-specific throttles (TOTP verify, static recovery codes) in one place.
These are framework-specific (DRF) concerns, not business logic.
"""

from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class _ScopedIdentityThrottle(SimpleRateThrottle):
    """Base throttle that prefers user/email identity, then falls back to client IP."""

    def _identity(self, request) -> str:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return f"user:{getattr(user, 'pk', user.id)}"

        email = None
        data = getattr(request, "data", None)
        if isinstance(data, dict):
            email = data.get("email")
        if not email:
            email = request.query_params.get("email")
        if email:
            return f"email:{str(email).strip().lower()}"

        return f"ip:{self.get_ident(request)}"

    def get_cache_key(self, request, view):
        ident = self._identity(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class _ScopedPrincipalThrottle(SimpleRateThrottle):
    """Base throttle keyed to authenticated user or client IP."""

    def get_cache_key(self, request, view):
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            ident = str(getattr(user, "pk", user.id))
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


# ---------------------------------------------------------------------------
# Authentication throttles
# ---------------------------------------------------------------------------

class LoginThrottle(_ScopedIdentityThrottle):
    scope = "auth_login"
    rate = "10/min"


class PasswordResetRequestThrottle(_ScopedIdentityThrottle):
    scope = "auth_password_reset_request"
    rate = "5/hour"


class PasswordResetConfirmThrottle(_ScopedIdentityThrottle):
    scope = "auth_password_reset_confirm"
    rate = "10/hour"


class EmailVerifyThrottle(_ScopedIdentityThrottle):
    scope = "auth_email_verify"
    rate = "15/hour"


class MagicLinkRequestThrottle(_ScopedIdentityThrottle):
    """Anonymous magic-link request throttle.

    Tight rate (5/hour per email+IP) because this endpoint sends real
    email — an attacker who could enumerate accounts by flooding it
    would also blow up the SES bounce/complaint rate.
    """

    scope = "auth_magic_link_request"
    rate = "5/hour"


class MagicLinkVerifyThrottle(_ScopedIdentityThrottle):
    """Verify-side throttle.

    Defence-in-depth against brute-force guessing of the 256-bit
    token. The token itself is uncrackable in any realistic horizon,
    but a flood of verify attempts is still an early-warning signal
    worth rate-limiting.
    """

    scope = "auth_magic_link_verify"
    rate = "10/hour"


# ---------------------------------------------------------------------------
# OTP / 2FA throttles
# ---------------------------------------------------------------------------

class OTPVerifyThrottle(_ScopedPrincipalThrottle):
    """Throttle OTP verification attempts per principal."""

    scope = "otp_verify"
    rate = "10/min"


class StaticVerifyThrottle(_ScopedPrincipalThrottle):
    """Throttle static recovery code verification attempts per principal."""

    scope = "otp_static_verify"
    rate = "5/min"
