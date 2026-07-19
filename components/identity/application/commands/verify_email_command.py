"""Command and result value objects for the verify-email use case.

No framework dependency — just typed data carriers.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.identity.domain.value_objects.auth_tokens import RequestContext


@dataclass(frozen=True)
class VerifyEmailCommand:
    """Input for the verify-email use case."""

    token: str
    context: RequestContext


@dataclass(frozen=True)
class VerifyEmailResult:
    """Output of a successful email verification."""

    user_id: UUID
    email: str
    username: str
    is_onboard_complete: bool
    is_contributor: bool
    tokens: dict


@dataclass(frozen=True)
class VerifyEmailFailure:
    """Represents a verification failure."""

    reason: str
    message: str
