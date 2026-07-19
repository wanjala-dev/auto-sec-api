"""Port for token revocation (logout / session invalidation)."""

from __future__ import annotations

import abc
from typing import Any


class TokenRevocationPort(abc.ABC):
    """Abstract interface for invalidating user authentication tokens."""

    @abc.abstractmethod
    def revoke_all_tokens(self, *, user_id: Any) -> int:
        """Blacklist all outstanding tokens for the given user.

        Returns the number of tokens revoked.
        """

    @abc.abstractmethod
    def revoke_token(self, *, token_string: str) -> bool:
        """Blacklist a single refresh token.

        Returns True if the token was found and blacklisted.
        """

    @abc.abstractmethod
    def revoke_by_jti(self, *, jti: str) -> bool:
        """Blacklist the single outstanding refresh token with this jti.

        Returns True if the token was found and newly blacklisted.
        """
