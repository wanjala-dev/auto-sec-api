"""Port for the passwordless magic-link sign-in flow.

Two operations:

  ``mint_token``    — write a new single-use token row for the email,
                      return a small DTO the controller can put in the
                      outgoing email.
  ``consume_token`` — atomically validate + mark consumed + look up or
                      create the user + issue a fresh JWT pair, return
                      a DTO matching the LoginAPIView response shape.

Splitting infrastructure (Django ORM + JWT issuance) from the use case
keeps the application layer framework-free per the identity bounded-
context import rules (``tests/architecture/test_identity_application_*``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MintedMagicLinkToken:
    email: str
    token: str
    next_url: str
    ttl_minutes: int


@dataclass(frozen=True)
class VerifiedMagicLinkSession:
    """DTO matching the LoginAPIView response shape so the frontend
    session plumbing works unchanged on the verify path."""

    user_id: str
    email: str
    username: str
    is_onboard_complete: bool
    is_contributor: bool
    access_token: str
    refresh_token: str
    next_url: str
    created_user: bool
    # Session anchors for the freshly minted refresh token (jti is stable —
    # refresh rotation is off). None when issuance didn't expose them.
    refresh_jti: str | None = None
    refresh_expires_at: datetime | None = None


class MagicLinkPort(ABC):
    """Application-layer port for the magic-link sign-in flow."""

    @abstractmethod
    def mint_token(
        self,
        *,
        email: str,
        next_url: str,
        ttl_minutes: int,
    ) -> MintedMagicLinkToken | None:
        """Create a fresh single-use token row for `email`.

        Returns ``None`` only on degenerate inputs (e.g. blank
        email) — the controller should silently no-op rather than
        leak the rejection to the caller.
        """

    @abstractmethod
    def consume_token(
        self,
        *,
        token_value: str,
        request_ip: str | None,
    ) -> VerifiedMagicLinkSession | None:
        """Validate + consume a token + issue tokens for the user.

        Returns ``None`` when the token is missing, expired, or
        already consumed. The controller maps that to a 400 with a
        generic "invalid or expired" message.
        """
