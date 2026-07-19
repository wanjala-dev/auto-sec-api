from components.shared_kernel.application.model_notification_rule_service import (
    ModelNotificationRuleService,
)
from components.shared_kernel.application.providers.model_notification_provider import (
    ModelNotificationProvider,
)
from components.shared_kernel.infrastructure.adapters.django_notification_dispatch_adapter import (
    DjangoNotificationDispatchAdapter,
)


def test_model_notification_provider_builds_rule_service():
    provider = ModelNotificationProvider()

    service = provider.build_rule_service()

    assert isinstance(service, ModelNotificationRuleService)
    assert isinstance(service.notification_dispatch_port, DjangoNotificationDispatchAdapter)
