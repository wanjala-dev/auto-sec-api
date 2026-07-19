from __future__ import annotations

from components.shared_kernel.application.model_notification_rule_service import (
    ModelNotificationRuleService,
)
from components.shared_kernel.infrastructure.adapters.django_notification_dispatch_adapter import (
    DjangoNotificationDispatchAdapter,
)


class ModelNotificationProvider:
    def build_rule_service(self) -> ModelNotificationRuleService:
        return ModelNotificationRuleService(
            notification_dispatch_port=DjangoNotificationDispatchAdapter(),
        )
