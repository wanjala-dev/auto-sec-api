"""Port for credential authentication.

The application layer calls this port to verify user credentials;
infrastructure provides the adapter that wraps Django auth.authenticate.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.identity.domain.entities.user_entity import UserEntity


class AuthenticationPort(ABC):
    """Secondary/driven port for credential verification."""

    @abstractmethod
    def authenticate(self, email: str, password: str) -> UserEntity | None:
        """Verify credentials and return the user entity, or None if invalid."""
        ...

    @abstractmethod
    def find_by_email(self, email: str) -> UserEntity | None:
        """Look up a user entity by email without credential check."""
        ...

    @abstractmethod
    def get_auth_provider(self, email: str) -> str | None:
        """Return the auth_provider for a user with this email, or None."""
        ...
