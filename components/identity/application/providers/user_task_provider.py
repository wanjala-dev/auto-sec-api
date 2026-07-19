"""Provider for identity Celery tasks (notify_security_event, etc.).

Lazy-imports the task callable so the controller's import graph
stays free of infrastructure.
"""

from __future__ import annotations

from typing import Any


class UserTaskProvider:
    def notify_security_event(self) -> Any:
        from components.identity.infrastructure.tasks.user_tasks import (
            notify_security_event,
        )

        return notify_security_event


_default = UserTaskProvider()


def get_user_task_provider() -> UserTaskProvider:
    return _default
