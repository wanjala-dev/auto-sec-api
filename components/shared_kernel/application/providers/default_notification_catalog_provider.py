from __future__ import annotations

from components.shared_kernel.infrastructure.adapters.default_notification_rule_catalog import (
    register_default_notification_rules,
)


class DefaultNotificationCatalogProvider:
    def register_defaults(self) -> None:
        register_default_notification_rules()
