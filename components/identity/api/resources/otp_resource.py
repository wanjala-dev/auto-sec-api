from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class OTPSetupResource:
    """Output DTO for GET /otp/create/ endpoint response.

    Returns provisioning URL for TOTP setup in authenticator apps.
    """
    otpauth_url: str


@dataclass(frozen=True)
class OTPVerifyResource:
    """Output DTO for POST /otp/verify/ and /otp/static/verify/ endpoint responses.

    Returns verification status and tokens after OTP code verification.
    """
    otp_verified: bool
    tokens: dict | None = None


@dataclass(frozen=True)
class StaticRecoveryCodesResource:
    """Output DTO for POST /otp/static/create/ endpoint response.

    Returns generated static recovery codes for account recovery.
    """
    recovery_codes: list[str]


@dataclass(frozen=True)
class OTPDisableResource:
    """Output DTO for POST /otp/delete/ endpoint response.

    Returns confirmation that 2FA has been disabled.
    """
    two_factor_enabled: bool
    tokens: dict | None = None
