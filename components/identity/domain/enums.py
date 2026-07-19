"""Canonical domain enums for the Identity bounded context.

These enums are the single source of truth for identity-related constants.
ORM model fields, serializers, and application code should reference these
instead of defining their own string literals.
"""

from enum import Enum


class AuthProvider(str, Enum):
    EMAIL = "email"
    GOOGLE = "google"


class AuthEventCode(str, Enum):
    LOGIN = "auth.login"
    LOGIN_FAILED = "auth.login_failed"
    OTP_VERIFY = "auth.otp_verify"
    OTP_VERIFY_FAILED = "auth.otp_verify_failed"
    PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"
    PASSWORD_RESET_COMPLETED = "auth.password_reset_completed"
    EMAIL_VERIFY = "auth.email_verify"
    LOGOUT = "auth.logout"
    PASSWORD_CHANGED = "auth.password_changed"
    SESSION_REVOKED = "auth.session_revoked"


# The "login-ish" subset of audit events surfaced on the org-level
# login-activity view (T2-S4). Single source of truth — the controller,
# the workspace read repository, and the tests all reference this tuple.
LOGIN_ACTIVITY_EVENT_CODES: tuple[str, ...] = (
    AuthEventCode.LOGIN.value,
    AuthEventCode.LOGIN_FAILED.value,
    AuthEventCode.LOGOUT.value,
    AuthEventCode.SESSION_REVOKED.value,
)


# Lockout policy constants — domain-owned, not infrastructure.
LOCKOUT_WINDOW_MINUTES: int = 30
LOCKOUT_THRESHOLD: int = 10
LOCKOUT_WARN_AT: int = 7
