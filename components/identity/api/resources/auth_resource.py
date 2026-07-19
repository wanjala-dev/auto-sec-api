from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class TokenPairResource:
    """Output DTO for JWT token pairs.

    Contains access and refresh tokens issued to authenticated users.
    NOTE: Token strings themselves are not DTOs per se, but are wrapped
    in this structure for schema clarity.
    """
    access: str
    refresh: str


@dataclass(frozen=True)
class RegisterUserResource:
    """Output DTO for POST /register/ endpoint response.

    Returns minimal user identification after successful registration.
    """
    uuid: list[dict]
    email: str
    username: str
    warning: str | None = None


@dataclass(frozen=True)
class LoginResource:
    """Output DTO for POST /login/ endpoint response.

    Returns authentication tokens and user onboarding state.
    """
    pk: str
    email: str
    username: str
    tokens: TokenPairResource
    is_onboard_complete: bool | None = None
    is_contributor: bool | None = None
    two_factor_enabled: bool | None = None
    two_factor_confirmed_at: str | None = None
    otp_required: bool | None = None
    preauth_token: str | None = None
    requires_org_onboarding: bool | None = None
    org_membership_count: int | None = None
    workspaces: list[dict] | None = None
    teams: list[dict] | None = None


@dataclass(frozen=True)
class EmailVerificationResource:
    """Output DTO for GET /email-verify/ endpoint response.

    Returns user data and tokens after email verification.
    """
    pk: str
    email: str
    username: str
    tokens: TokenPairResource
    is_onboard_complete: bool | None = None
    is_contributor: bool | None = None
    detail: str | None = None


@dataclass(frozen=True)
class PasswordResetRequestResource:
    """Output DTO for POST /request-reset-email/ endpoint response.

    Returns confirmation message after password reset email is sent.
    """
    success: str


@dataclass(frozen=True)
class SetNewPasswordResource:
    """Output DTO for PATCH /password-reset-complete/ endpoint response.

    Returns confirmation message after password reset is completed.
    """
    success: bool
    message: str


@dataclass(frozen=True)
class ChangePasswordResource:
    """Output DTO for PATCH /changepassword/ endpoint response.

    Returns confirmation message after password change.
    """
    status: str
    code: int
    message: str
