"""Port for the platform-agnostic push device registry (T1-S5).

The application layer registers/revokes/queries push devices through this
port; infrastructure provides the ORM adapter over ``PushSubscription``.
Identity is ``endpoint_hash`` (sha256 hex of the endpoint) — see
``components.notifications.domain.value_objects.push_endpoint``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PushSubscriptionRecord:
    """Framework-free projection of one registered push device."""

    id: str
    user_id: str
    platform: str
    endpoint: str
    endpoint_hash: str
    keys: dict[str, Any]
    device_label: str
    status: str
    last_seen_at: datetime | None = None


@dataclass(frozen=True)
class UpsertOutcome:
    """Result of an upsert — the (possibly refreshed) record and whether a
    new device row was created (False = existing registration updated)."""

    record: PushSubscriptionRecord
    created: bool


class PushSubscriptionRegistryPort(ABC):
    """Secondary/driven port for push device registration state."""

    @abstractmethod
    def upsert_by_endpoint(
        self,
        *,
        user_id,
        endpoint: str,
        endpoint_hash: str,
        keys: dict[str, Any] | None = None,
        device_label: str = "",
        user_agent: str = "",
        platform: str = "web",
    ) -> UpsertOutcome:
        """Create or refresh the registration keyed on ``endpoint_hash``.

        Re-subscribing an existing endpoint MUST update the row in place
        (keys/label/user-agent/platform, re-activate, bump ``last_seen_at``)
        — never create a duplicate.
        """
        ...

    @abstractmethod
    def revoke_by_endpoint_hash(self, *, user_id, endpoint_hash: str) -> bool:
        """Mark the user's registration revoked. Idempotent — returns True
        when a row was transitioned, False when nothing matched (already
        revoked or never registered)."""
        ...

    @abstractmethod
    def list_active_for_user(self, user_id, *, platform: str | None = None) -> list[PushSubscriptionRecord]:
        """Return the user's ACTIVE registrations (optionally one platform)."""
        ...

    @abstractmethod
    def get_by_id(self, subscription_id) -> PushSubscriptionRecord | None:
        """Return one registration by primary key (any status), or None.

        Senders resolve a ledger row's ``subscription_id`` to the endpoint
        + crypto keys through this — and check ``status`` before
        transmitting."""
        ...

    @abstractmethod
    def mark_expired(self, subscription_id) -> None:
        """Transition a registration to ``expired`` (push service returned
        404/410 for its endpoint). Idempotent."""
        ...
