"""Command and result value objects for the password reset use cases.

No framework dependency — just typed data carriers.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.identity.domain.value_objects.auth_tokens import RequestContext


@dataclass(frozen=True)
class RequestPasswordResetCommand:
    """Input for requesting a password reset email."""

    email: str
    reset_base_url: str
    redirect_url: str
    context: RequestContext


@dataclass(frozen=True)
class RequestPasswordResetResult:
    """Output — always returns success message to prevent email enumeration."""

    message: str = "We have sent you a link to reset your password"


@dataclass(frozen=True)
class SetNewPasswordCommand:
    """Input for setting a new password after reset."""

    uidb64: str
    token: str
    new_password: str
    context: RequestContext


@dataclass(frozen=True)
class SetNewPasswordResult:
    """Output of a successful password reset."""

    success: bool = True
    message: str = "Password reset success"


@dataclass(frozen=True)
class SetNewPasswordFailure:
    """Represents a password reset failure."""

    reason: str
    message: str
