from components.shared_kernel.application.model_notification_rule_service import (
    ModelNotificationRuleService,
)
from components.shared_kernel.application.providers.model_notification_registry_provider import (
    ModelNotificationRegistryProvider,
)
from components.shared_kernel.infrastructure.adapters.django_model_notification_registry import (
    DjangoModelNotificationRegistry,
)


def test_model_notification_registry_provider_builds_registry():
    registry = ModelNotificationRegistryProvider().build_registry()

    assert isinstance(registry, DjangoModelNotificationRegistry)
    assert isinstance(registry.rule_service, ModelNotificationRuleService)
