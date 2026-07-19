"""Port for notification persistence and query operations.

The application layer calls this port; infrastructure provides the ORM adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from components.notifications.domain.entities.notification_entity import (
    NotificationEntity,
)
from components.notifications.domain.value_objects.notification_filter import (
    NotificationFilter,
)


@dataclass(frozen=True)
class MarkReadOutcome:
    """Result of marking one notification read.

    Carries the recipient/workspace so the use case can publish the read
    event to the recipient's realtime stream without a second lookup.
    ``changed`` is False when the row was already read or doesn't exist
    (recipient/workspace are None in the missing case).
    """

    changed: bool
    recipient_id: str | None = None
    workspace_id: str | None = None


class NotificationRepositoryPort(ABC):
    """Secondary/driven port for notification read/write operations."""

    @abstractmethod
    def list_notifications(self, criteria: NotificationFilter) -> list[NotificationEntity]:
        """Return notifications matching the given filter criteria."""
        ...

    @abstractmethod
    def find_by_id(self, notification_id: int) -> NotificationEntity | None: ...

    @abstractmethod
    def mark_read(self, notification_id: int) -> MarkReadOutcome:
        """Mark a single notification as read.

        Returns a :class:`MarkReadOutcome` — ``changed`` True only when
        the row flipped from unread to read.
        """
        ...

    @abstractmethod
    def mark_all_read(self, user_id: UUID, *, workspace_id: UUID | None = None) -> int:
        """Mark all unread notifications for a user as read.

        Returns the count of updated notifications.
        """
        ...

    @abstractmethod
    def unread_count(self, user_id: UUID, *, workspace_id: UUID | None = None) -> int: ...
