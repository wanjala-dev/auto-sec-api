"""Use case: revoke a push device registration.

Idempotent by design — revoking an unknown or already-revoked endpoint is a
success (the desired end state holds), so the DELETE endpoint can always
return 204. Accepts either the raw endpoint or its hash.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.notifications.application.ports.push_subscription_registry_port import (
    PushSubscriptionRegistryPort,
)
from components.notifications.domain.errors import NotificationValidationError
from components.notifications.domain.value_objects.push_endpoint import (
    ENDPOINT_HASH_LENGTH,
    derive_endpoint_hash,
)


@dataclass
class RevokePushSubscriptionUseCase:
    registry: PushSubscriptionRegistryPort

    def execute(
        self,
        *,
        user_id,
        endpoint: str | None = None,
        endpoint_hash: str | None = None,
    ) -> bool:
        """Revoke by endpoint or endpoint_hash. Returns whether a row
        actually transitioned (callers treat both outcomes as success)."""
        endpoint_hash = (endpoint_hash or "").strip().lower()
        if endpoint_hash and len(endpoint_hash) != ENDPOINT_HASH_LENGTH:
            raise NotificationValidationError("endpoint_hash must be a sha256 hex digest")
        if not endpoint_hash:
            if not (endpoint or "").strip():
                raise NotificationValidationError("endpoint or endpoint_hash is required")
            endpoint_hash = derive_endpoint_hash(endpoint)

        return self.registry.revoke_by_endpoint_hash(
            user_id=user_id,
            endpoint_hash=endpoint_hash,
        )
