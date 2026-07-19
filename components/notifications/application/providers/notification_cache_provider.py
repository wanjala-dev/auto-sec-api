"""Provider/composition root for the notification preference-cache adapter.

Controllers (``components/notifications/api/controller.py``) consume
:class:`NotificationCacheProvider` instead of importing the concrete
``components.notifications.infrastructure.adapters.notification_service``
module directly. Keeps the API layer's import graph free of infrastructure
dependencies (Django cache, models) and lets the
``test_controllers_do_not_import_concrete_adapters`` architecture test stay
green.

All adapter imports are deferred to method bodies so module load is cheap
and tests can monkeypatch ``_default`` without dragging Django into test
discovery.
"""

from __future__ import annotations

from typing import Any


class NotificationCacheProvider:
    """Driving-side facade for the notification preference cache adapter."""

    def invalidate_preference_cache(
        self,
        user_id: Any,
        workspace_id: Any | None = None,
    ) -> None:
        """Flush cached notification-preference decisions for a user+workspace.

        Mirrors
        :func:`components.notifications.infrastructure.adapters.notification_service.invalidate_preference_cache`.
        """
        from components.notifications.infrastructure.adapters.notification_service import (
            invalidate_preference_cache as _invalidate,
        )

        return _invalidate(user_id, workspace_id)


_default = NotificationCacheProvider()


def get_notification_cache_provider() -> NotificationCacheProvider:
    """Return the default provider — composition root for the notification
    preference cache adapter. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
