"""Value objects for authentication tokens.

No framework dependency — just typed data carriers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuthTokenPair:
    """Immutable token pair issued after successful authentication.

    ``refresh_jti`` / ``refresh_expires_at`` identify the refresh token that
    anchors a login session (jti is stable — refresh-token rotation is off).
    They are ``None`` when no refresh token was issued.
    """

    access: str
    refresh: str | None = None
    refresh_jti: str | None = None
    refresh_expires_at: datetime | None = None


@dataclass(frozen=True)
class PreAuthToken:
    """Short-lived token issued when 2FA verification is still pending."""

    access: str
    requires_otp: bool = True


@dataclass(frozen=True)
class RequestContext:
    """Extracted request metadata for audit purposes."""

    ip_address: str | None
    user_agent: str
