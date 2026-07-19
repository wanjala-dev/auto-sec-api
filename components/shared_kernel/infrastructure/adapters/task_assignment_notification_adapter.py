from __future__ import annotations

from django.contrib.auth import get_user_model

from infrastructure.persistence.notifications.models import Notification
from components.notifications.infrastructure.adapters.notification_service import NotificationDispatcher

User = get_user_model()


class TaskAssignmentNotificationAdapter:
    def __init__(self) -> None:
        self.dispatcher = NotificationDispatcher()

    def notify_assignment_change(
        self,
        *,
        task,
        actor,
        recipient_ids,
        action: str,
    ) -> None:
        if action not in ("post_add", "post_remove") or actor is None or not recipient_ids:
            return

        recipients = list(User.objects.filter(pk__in=recipient_ids))
        if not recipients:
            return

        verb = (
            'assigned you to task "{label}"'
            if action == "post_add"
            else 'removed you from task "{label}"'
        )
        event_suffix = "added" if action == "post_add" else "removed"

        self.dispatcher.dispatch(
            actor=actor,
            workspace=task.workspace,
            verb=verb.format(label=task.title),
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=recipients,
            metadata={
                "event": f"tasks.assignment_{event_suffix}",
                "task": str(task.pk),
            },
            target=task,
        )
