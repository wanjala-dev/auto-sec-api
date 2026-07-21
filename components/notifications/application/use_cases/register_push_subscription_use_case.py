"""Use case: register (or refresh) a push device for a user.

Upsert keyed on ``sha256(endpoint)`` — re-subscribing an existing endpoint
updates the registration in place instead of duplicating the device.
Framework-free: depends only on the registry port + domain helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from components.notifications.application.ports.push_subscription_registry_port import (
    PushSubscriptionRegistryPort,
    UpsertOutcome,
)
from components.notifications.domain.enums import PushPlatform
from components.notifications.domain.errors import NotificationValidationError
from components.notifications.domain.value_objects.push_endpoint import derive_endpoint_hash

# Web-push subscriptions must carry the browser's crypto material or the
# sender (T1-S6) can never encrypt a payload for them.
_WEB_REQUIRED_KEYS = ("p256dh", "auth")


@dataclass
class RegisterPushSubscriptionUseCase:
    registry: PushSubscriptionRegistryPort

    def execute(
        self,
        *,
        user_id,
        endpoint: str,
        keys: dict[str, Any] | None = None,
        device_label: str = "",
        user_agent: str = "",
        platform: str = PushPlatform.WEB.value,
    ) -> UpsertOutcome:
        endpoint = (endpoint or "").strip()
        if not endpoint:
            raise NotificationValidationError("endpoint is required")

        if platform not in {p.value for p in PushPlatform}:
            raise NotificationValidationError(f"unsupported push platform: {platform!r}")

        keys = dict(keys or {})
        if platform == PushPlatform.WEB.value:
            missing = [name for name in _WEB_REQUIRED_KEYS if not keys.get(name)]
            if missing:
                raise NotificationValidationError(f"web push subscriptions require keys: {', '.join(missing)}")

        return self.registry.upsert_by_endpoint(
            user_id=user_id,
            endpoint=endpoint,
            endpoint_hash=derive_endpoint_hash(endpoint),
            keys=keys,
            device_label=(device_label or "")[:255],
            user_agent=user_agent or "",
            platform=platform,
        )
