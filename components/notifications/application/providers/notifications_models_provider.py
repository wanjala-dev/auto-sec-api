"""Provider for notifications ORM model classes.

Controllers that previously imported Django ORM models from
``infrastructure.persistence.notifications`` now go through this provider
instead. The controller layer never imports ORM classes directly; the
provider lazy-imports them inside method bodies so the module itself is
framework-free at import time (only stdlib + typing).

Expose one property per model class encountered across the
``infrastructure.persistence.notifications`` package (top-level + sub-modules
like ``userpreferences.models``). Add new models here as controllers grow.
"""

from __future__ import annotations

from typing import Any


class NotificationsModelsProvider:
    """Lazy provider for notifications bounded-context ORM models.

    Each property defers the ``infrastructure.persistence.notifications``
    import until first access so this module stays Django-free at top level.
    """

    # ── notifications.models ────────────────────────────────────────────

    @property
    def Notification(self) -> Any:
        from infrastructure.persistence.notifications.models import Notification
        return Notification

    @property
    def WorkspaceNotificationPreference(self) -> Any:
        from infrastructure.persistence.notifications.models import (
            WorkspaceNotificationPreference,
        )
        return WorkspaceNotificationPreference

    @property
    def AINotificationPreference(self) -> Any:
        from infrastructure.persistence.notifications.models import (
            AINotificationPreference,
        )
        return AINotificationPreference

    # ── notifications.userpreferences.models ────────────────────────────

    @property
    def UserPreference(self) -> Any:
        from infrastructure.persistence.notifications.userpreferences.models import (
            UserPreference,
        )
        return UserPreference

    @property
    def WorkspacePreference(self) -> Any:
        from infrastructure.persistence.notifications.userpreferences.models import (
            WorkspacePreference,
        )
        return WorkspacePreference


_default = NotificationsModelsProvider()


def get_notifications_models_provider() -> NotificationsModelsProvider:
    """Return the default :class:`NotificationsModelsProvider` instance."""
    return _default
