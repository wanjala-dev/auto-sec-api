"""Ports for the Google (OpenID Connect) sign-in flow.

Two separable concerns, two ports, so each can be faked in isolation:

  ``GoogleTokenVerifierPort`` — turn a raw Google ID token into a
      trusted ``GoogleIdentity`` (or ``None``). The only place that
      talks to Google's verification libraries. Faking this in a test
      lets us exercise the whole sign-in path without a live token.

  ``GoogleAuthPort`` — atomically look up or create the user for a
      verified identity + issue a fresh JWT pair, returning a DTO
      matching the ``LoginAPIView`` response shape so the frontend
      session plumbing works unchanged.

Splitting infrastructure (Google libs, Django ORM, JWT issuance) from
the use case keeps the application layer framework-free per the
identity bounded-context import rules
(``tests/architecture/test_identity_application_*``). This mirrors the
passwordless ``MagicLinkPort`` design deliberately — Google sign-in is
just another passwordless path that converges on the same session DTO.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class GoogleIdentity:
    """A verified Google identity — the trustworthy subset of the
    ID-token claims after signature, audience, issuer and
    email-verification checks have all passed."""

    sub: str
    email: str
    email_verified: bool
    name: str
    picture: str = ""


@dataclass(frozen=True)
class VerifiedGoogleSession:
    """DTO matching the ``LoginAPIView`` response shape so the frontend
    session plumbing works unchanged on the Google path."""

    user_id: str
    email: str
    username: str
    is_onboard_complete: bool
    is_contributor: bool
    access_token: str
    refresh_token: str
    created_user: bool
    # Session anchors for the freshly minted refresh token (jti is stable —
    # refresh rotation is off). None when issuance didn't expose them.
    refresh_jti: str | None = None
    refresh_expires_at: datetime | None = None


@dataclass(frozen=True)
class GoogleAuthError:
    """A clean, user-safe failure. ``message`` is safe to surface;
    ``code`` lets the frontend branch (e.g. steer a user who already
    has an email/password account to that login)."""

    code: str
    message: str
    status: int


class GoogleTokenVerifierPort(ABC):
    """Verify a raw Google ID token and return the trusted identity."""

    @abstractmethod
    def verify(self, raw_token: str) -> GoogleIdentity | None:
        """Return a ``GoogleIdentity`` when the token's signature,
        audience, issuer and ``email_verified`` claim all check out;
        ``None`` otherwise. Never raises for an untrusted token — the
        caller maps ``None`` to a generic 401."""


class GoogleAuthPort(ABC):
    """Look up or create the user for a verified Google identity and
    issue a JWT session."""

    @abstractmethod
    def authenticate(
        self,
        *,
        identity: GoogleIdentity,
        request_ip: str | None = None,
    ) -> VerifiedGoogleSession | GoogleAuthError:
        """Resolve the user for ``identity`` (link by Google ``sub``
        first, then by verified email), creating a passwordless account
        on first sign-in, and issue a fresh JWT pair. Returns a
        ``GoogleAuthError`` for recoverable conflicts (e.g. the email
        already belongs to a non-Google account)."""
