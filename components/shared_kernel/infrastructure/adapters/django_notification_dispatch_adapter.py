from __future__ import annotations

from components.notifications.infrastructure.adapters.notification_service import NotificationDispatcher


class DjangoNotificationDispatchAdapter:
    def __init__(self) -> None:
        self.dispatcher = NotificationDispatcher()

    def dispatch(
        self,
        *,
        actor,
        workspace,
        verb: str,
        notification_type: str,
        recipients,
        metadata: dict | None = None,
        target=None,
    ) -> None:
        self.dispatcher.dispatch(
            actor=actor,
            workspace=workspace,
            verb=verb,
            notification_type=notification_type,
            recipients=recipients,
            metadata=metadata,
            target=target,
        )
