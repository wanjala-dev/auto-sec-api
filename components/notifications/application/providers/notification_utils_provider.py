"""Provider for notification utility functions (create_notification, …).

Cross-context callers (team) consume this provider instead of
importing
``components.notifications.infrastructure.adapters.utils`` directly.
"""

from __future__ import annotations

from typing import Any


class NotificationUtilsProvider:
    def create_notification(self, *args, **kwargs) -> Any:
        from components.notifications.infrastructure.adapters.utils import (
            create_notification,
        )

        return create_notification(*args, **kwargs)


_default = NotificationUtilsProvider()


def get_notification_utils_provider() -> NotificationUtilsProvider:
    return _default
