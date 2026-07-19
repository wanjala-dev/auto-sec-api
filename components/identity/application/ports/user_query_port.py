"""Port for user query operations.

The application layer calls this port for read-only queries; infrastructure provides the ORM adapter.
These are query helpers that bypass the standard UserRepositoryPort and return raw ORM models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class UserQueryPort(ABC):
    """Secondary/driven port for user query operations.

    This port handles read-only queries that return raw ORM models or querysets,
    which are needed for controller/serialization logic but don't fit the domain entity pattern.
    """

    @abstractmethod
    def get_by_id(self, user_id, with_profile: bool = False):
        """Get user by ID, optionally with profile pre-fetched.

        Returns the ORM model or None if not found.
        """
        ...

    @abstractmethod
    def get_by_email(self, email: str):
        """Get user by email.

        Returns the ORM model or None if not found.
        """
        ...

    @abstractmethod
    def find_by_email_and_username(self, email: str, username: str):
        """Find users matching email and username.

        Returns a queryset of matching users.
        """
        ...

    @abstractmethod
    def get_queryset(self):
        """Return the base user queryset with profile pre-fetched.

        Returns a queryset with select_related for profile and contributor_profile.
        """
        ...

    @abstractmethod
    def get_profile(self, user_id):
        """Get user profile by user ID.

        Returns the ORM profile model or None if not found.
        """
        ...

    @abstractmethod
    def list_pending_invitations(self, email: str):
        """List pending invitations for an email.

        Returns a queryset of pending invitations ordered by descending ID.
        """
        ...

    @abstractmethod
    def get_system_actor(self):
        """Get system actor (superuser or staff) for audit events.

        Returns a user model (superuser or staff) or None if not found.
        """
        ...
