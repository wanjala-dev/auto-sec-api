"""Composition root for the Notifications bounded context.

This provider wires concrete infrastructure adapters to application use cases.
Controllers call this provider to get fully composed use case instances.
"""

from __future__ import annotations

from components.notifications.application.queries.list_notifications_query import (
    ListNotificationsQuery,
)
from components.notifications.application.use_cases.mark_all_notifications_read_use_case import (
    MarkAllNotificationsReadUseCase,
)
from components.notifications.application.use_cases.mark_notification_read_use_case import (
    MarkNotificationReadUseCase,
)
from components.notifications.infrastructure.adapters.realtime_notification_channel import (
    RealtimeNotificationChannel,
)
from components.notifications.infrastructure.repositories.orm_notification_repository import (
    OrmNotificationRepository,
)


class NotificationsProvider:
    """Composition root that builds fully-wired use case instances."""

    @staticmethod
    def build_notification_repository() -> OrmNotificationRepository:
        return OrmNotificationRepository()

    @staticmethod
    def build_mark_notification_read_use_case() -> MarkNotificationReadUseCase:
        return MarkNotificationReadUseCase(
            notification_repo=OrmNotificationRepository(),
            notification_channel=RealtimeNotificationChannel(),
        )

    @staticmethod
    def build_mark_all_notifications_read_use_case() -> MarkAllNotificationsReadUseCase:
        return MarkAllNotificationsReadUseCase(
            notification_repo=OrmNotificationRepository(),
            notification_channel=RealtimeNotificationChannel(),
        )

    @staticmethod
    def build_list_notifications_query() -> ListNotificationsQuery:
        return ListNotificationsQuery(
            notification_repo=OrmNotificationRepository(),
        )
