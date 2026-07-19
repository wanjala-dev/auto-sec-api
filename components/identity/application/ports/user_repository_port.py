"""Port for user persistence operations.

The application layer calls this port; infrastructure provides the ORM adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.identity.domain.entities.user_entity import UserEntity
from components.identity.domain.entities.user_profile_entity import UserProfileEntity


class UserRepositoryPort(ABC):
    """Secondary/driven port for user read/write operations."""

    @abstractmethod
    def find_by_id(self, user_id: UUID) -> UserEntity | None:
        ...

    @abstractmethod
    def find_by_email(self, email: str) -> UserEntity | None:
        ...

    @abstractmethod
    def find_profile(self, user_id: UUID) -> UserProfileEntity | None:
        ...

    @abstractmethod
    def create_user(self, username: str, email: str, password: str) -> UserEntity:
        ...

    @abstractmethod
    def verify_email(self, user_id: UUID) -> None:
        ...

    @abstractmethod
    def set_password(self, user_id: UUID, new_password: str) -> None:
        ...

    @abstractmethod
    def check_password(self, user_id: UUID, password: str) -> bool:
        ...

    @abstractmethod
    def validate_new_password(self, user_id: UUID, password: str) -> list[str]:
        """Validate a new password against password policy rules.

        Returns an empty list if valid, or a list of validation error messages.
        """
        ...

    @abstractmethod
    def enable_two_factor(self, user_id: UUID) -> None:
        """Set two_factor_enabled=True and two_factor_confirmed_at=now()."""
        ...

    @abstractmethod
    def disable_two_factor(self, user_id: UUID) -> None:
        """Set two_factor_enabled=False and two_factor_confirmed_at=None."""
        ...
