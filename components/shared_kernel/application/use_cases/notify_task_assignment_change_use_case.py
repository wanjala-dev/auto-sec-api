from __future__ import annotations

from components.shared_kernel.application.ports.task_assignment_notification_port import (
    TaskAssignmentNotificationPort,
)


class NotifyTaskAssignmentChangeUseCase:
    def __init__(
        self,
        *,
        task_assignment_notification_port: TaskAssignmentNotificationPort,
    ) -> None:
        self.task_assignment_notification_port = task_assignment_notification_port

    def execute(
        self,
        *,
        task,
        actor,
        recipient_ids,
        action: str,
    ) -> None:
        self.task_assignment_notification_port.notify_assignment_change(
            task=task,
            actor=actor,
            recipient_ids=recipient_ids,
            action=action,
        )
