"""Port for JWT / authentication token issuance.

The application layer calls this port to issue tokens; infrastructure
provides the concrete adapter (e.g., SimpleJWT).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.identity.domain.value_objects.auth_tokens import AuthTokenPair, PreAuthToken


class TokenPort(ABC):
    """Secondary/driven port for token issuance."""

    @abstractmethod
    def issue_tokens(
        self,
        user_id: UUID,
        *,
        otp_verified: bool,
        device_id: int | None,
        include_refresh: bool,
    ) -> AuthTokenPair:
        """Issue a full token pair (access + optional refresh)."""
        ...

    @abstractmethod
    def issue_preauth_token(self, user_id: UUID, lifetime_minutes: int) -> PreAuthToken:
        """Issue a short-lived pre-auth token for pending 2FA."""
        ...

    @abstractmethod
    def issue_email_verification_token(self, user_id: UUID) -> str:
        """Issue the single-purpose token carried by a confirmation link.

        NOT an access token: it must be powerless as a credential, because it
        travels by plaintext email and then sits in an inbox. See
        ``email_verification_token.py``.
        """
        ...

    @abstractmethod
    def decode_email_verification_token(self, token: str) -> UUID | None:
        """Decode a confirmation-link token, or None if it is not one.

        Scope cuts both ways: a session credential must not be accepted here as
        proof of inbox control, so the token's type is checked, not just its
        signature.
        """
        ...

    # NOTE: there is deliberately no general-purpose ``decode_token`` here.
    # The one that used to exist decoded ANY token signed with the app key and
    # returned its ``user_id`` without inspecting ``token_type`` — which is how
    # a plain access token could be presented as proof of inbox control. Decode
    # methods on this port are scoped to one token type each; add a new scoped
    # method rather than reviving an unscoped one.
