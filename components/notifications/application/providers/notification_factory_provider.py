"""Provider/composition root for the notification factory adapter.

Controllers (``components/notifications/api/controller.py``) consume
:class:`NotificationFactoryProvider` instead of importing the concrete
``components.notifications.infrastructure.adapters.utils`` module directly.
Keeps the API layer's import graph free of infrastructure dependencies
(ContentType, ORM models) and lets the
``test_controllers_do_not_import_concrete_adapters`` architecture test stay
green.

All adapter imports are deferred to method bodies so module load is cheap
and tests can monkeypatch ``_default`` without dragging Django into test
discovery.
"""

from __future__ import annotations

from typing import Any


class NotificationFactoryProvider:
    """Driving-side facade for the ``create_notification`` adapter."""

    def create_notification(self, *args: Any, **kwargs: Any) -> Any:
        """Create (or reuse) a notification.

        Thin wrapper over
        :func:`components.notifications.infrastructure.adapters.utils.create_notification`
        — signature is forwarded verbatim so all keyword args (recipient,
        actor, verb, notification_type, target, workspace, metadata,
        deduplicate, deduplication_window, logo_url) pass through unchanged.
        """
        from components.notifications.infrastructure.adapters.utils import (
            create_notification as _create_notification,
        )

        return _create_notification(*args, **kwargs)

    def dispatch(self, *args: Any, **kwargs: Any) -> Any:
        """Fan a notification out through the canonical dispatcher funnel.

        Thin wrapper over the notifications context's
        ``NotificationDispatcher`` so cross-context APPLICATION layers (use
        cases) can reach the funnel without importing another context's
        infrastructure — the layer-purity and cross-context architecture
        tests forbid that. Signature is forwarded verbatim (actor, workspace,
        verb, notification_type, recipients, metadata, target, ai_channel,
        logo_url, allow_self_notify).
        """
        from components.notifications.infrastructure.adapters.notification_service import (
            NotificationDispatcher,
        )

        return NotificationDispatcher().dispatch(*args, **kwargs)


_default = NotificationFactoryProvider()


def get_notification_factory_provider() -> NotificationFactoryProvider:
    """Return the default provider — composition root for the
    ``create_notification`` adapter. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
