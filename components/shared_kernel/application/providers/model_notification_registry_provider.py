from __future__ import annotations

from components.shared_kernel.application.providers.model_notification_provider import (
    ModelNotificationProvider,
)
from components.shared_kernel.infrastructure.adapters.django_model_notification_registry import (
    DjangoModelNotificationRegistry,
)

_model_notification_registry: DjangoModelNotificationRegistry | None = None


class ModelNotificationRegistryProvider:
    def build_registry(self) -> DjangoModelNotificationRegistry:
        return DjangoModelNotificationRegistry(
            rule_service=ModelNotificationProvider().build_rule_service(),
        )


def get_model_notification_registry() -> DjangoModelNotificationRegistry:
    global _model_notification_registry
    if _model_notification_registry is None:
        _model_notification_registry = ModelNotificationRegistryProvider().build_registry()
    return _model_notification_registry


def register_model_notification_rule(rule) -> None:
    get_model_notification_registry().register(rule)
