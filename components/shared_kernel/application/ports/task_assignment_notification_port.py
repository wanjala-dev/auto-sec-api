from __future__ import annotations

from typing import Protocol, Sequence


class TaskAssignmentNotificationPort(Protocol):
    def notify_assignment_change(
        self,
        *,
        task,
        actor,
        recipient_ids: Sequence,
        action: str,
    ) -> None:
        ...
