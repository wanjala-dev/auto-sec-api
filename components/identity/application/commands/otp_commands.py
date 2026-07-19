"""Command and result value objects for OTP use cases.

No framework dependency — just typed data carriers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from components.identity.domain.value_objects.auth_tokens import RequestContext


# --- Setup ---

@dataclass(frozen=True)
class SetupOTPCommand:
    """Input for the setup-OTP use case."""

    user_id: UUID


@dataclass(frozen=True)
class SetupOTPResult:
    """Output of OTP device setup — contains the otpauth:// URL for QR code."""

    otpauth_url: str


# --- Verify ---

@dataclass(frozen=True)
class VerifyOTPCommand:
    """Input for the verify-OTP use case."""

    user_id: UUID
    email: str
    token: str
    method: str  # "totp" or "static"
    context: RequestContext


@dataclass(frozen=True)
class VerifyOTPResult:
    """Output of a successful OTP verification."""

    otp_verified: bool = True
    tokens: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VerifyOTPFailure:
    """Represents an OTP verification failure."""

    reason: str
    message: str
    locked: bool = False
    remaining_seconds: int = 0


# --- Disable ---

@dataclass(frozen=True)
class DisableOTPCommand:
    """Input for disabling 2FA."""

    user_id: UUID


@dataclass(frozen=True)
class DisableOTPResult:
    """Output of a successful 2FA disable."""

    two_factor_enabled: bool = False
    tokens: dict = field(default_factory=dict)
