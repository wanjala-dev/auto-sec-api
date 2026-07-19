"""Command and result value objects for the login use case.

No framework dependency — just typed data carriers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from components.identity.domain.value_objects.auth_tokens import (
    AuthTokenPair,
    PreAuthToken,
    RequestContext,
)


@dataclass(frozen=True)
class LoginCommand:
    """Input for the login use case."""

    email: str
    password: str
    context: RequestContext


@dataclass(frozen=True)
class LoginResult:
    """Output of a successful login use case execution."""

    user_id: UUID
    email: str
    username: str
    is_onboard_complete: bool
    is_contributor: bool
    two_factor_enabled: bool
    two_factor_confirmed_at: object | None  # datetime or None
    otp_required: bool
    preauth_token: str | None
    tokens: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LoginFailure:
    """Represents a login failure with reason details."""

    reason: str
    message: str
    locked: bool = False
    remaining_seconds: int = 0
    remaining_attempts: int = 0
    warn: bool = False
