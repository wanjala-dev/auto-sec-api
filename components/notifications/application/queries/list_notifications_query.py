"""List-notifications query — CQRS read side, no mutations."""

from __future__ import annotations

from components.notifications.domain.entities.notification_entity import (
    NotificationEntity,
)
from components.notifications.domain.value_objects.notification_filter import (
    NotificationFilter,
)
from components.notifications.application.ports.notification_repository_port import (
    NotificationRepositoryPort,
)


class ListNotificationsQuery:
    """Query handler for filtered notification listing."""

    def __init__(self, *, notification_repo: NotificationRepositoryPort) -> None:
        self._repo = notification_repo

    def execute(self, criteria: NotificationFilter) -> list[NotificationEntity]:
        return self._repo.list_notifications(criteria)
