"""Provider/composition root for the push registry + delivery ledger (T1-S5).

Controllers and workers consume this provider instead of importing the
concrete ORM repositories / settings readers directly, keeping the primary
adapters' import graph free of infrastructure dependencies (same pattern as
``notification_cache_provider``). All infrastructure imports are deferred to
method bodies; tests monkeypatch ``_default``.
"""

from __future__ import annotations


class PushDeliveryProvider:
    """Composition root for push subscription + delivery ledger wiring."""

    def push_subscription_registry(self):
        from components.notifications.infrastructure.repositories.orm_push_subscription_repository import (
            OrmPushSubscriptionRepository,
        )

        return OrmPushSubscriptionRepository()

    def delivery_ledger(self):
        from components.notifications.infrastructure.repositories.orm_delivery_ledger_repository import (
            OrmDeliveryLedgerRepository,
        )

        return OrmDeliveryLedgerRepository()

    def web_push_sender(self):
        from components.notifications.infrastructure.adapters.pywebpush_web_push_sender_adapter import (
            PywebpushWebPushSenderAdapter,
        )

        return PywebpushWebPushSenderAdapter()

    def build_register_push_subscription_use_case(self):
        from components.notifications.application.use_cases.register_push_subscription_use_case import (
            RegisterPushSubscriptionUseCase,
        )

        return RegisterPushSubscriptionUseCase(registry=self.push_subscription_registry())

    def build_revoke_push_subscription_use_case(self):
        from components.notifications.application.use_cases.revoke_push_subscription_use_case import (
            RevokePushSubscriptionUseCase,
        )

        return RevokePushSubscriptionUseCase(registry=self.push_subscription_registry())

    def channels_for(self, user):
        """Per-channel delivery gate — defers to the cached adapter."""
        from components.notifications.infrastructure.adapters.notification_service import (
            channels_for as _channels_for,
        )

        return _channels_for(user)

    def invalidate_channel_cache(self, user_id) -> None:
        from components.notifications.infrastructure.adapters.notification_service import (
            invalidate_channel_cache as _invalidate,
        )

        _invalidate(user_id)

    def vapid_public_key(self) -> str:
        """The VAPID application-server public key the frontend needs to call
        ``PushManager.subscribe`` — empty string until ops provisions keys."""
        from components.notifications.infrastructure.adapters.webpush_config import (
            get_vapid_public_key,
        )

        return get_vapid_public_key()


_default = PushDeliveryProvider()


def get_push_delivery_provider() -> PushDeliveryProvider:
    """Return the default provider. Override by monkeypatching this module's
    ``_default`` attribute in tests."""
    return _default
