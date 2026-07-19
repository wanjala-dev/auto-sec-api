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
    def decode_token(self, token: str) -> UUID | None:
        """Decode a JWT token and return the user_id, or None if invalid/expired."""
        ...
