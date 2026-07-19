"""Port for fanning a notification event out to a delivery channel.

One implementation per delivery channel (realtime websocket now; web push
and email land in later slices of the unified-pipeline track). The
dispatcher funnel calls every enabled channel after the in-app row —
the source of truth — is created, so a channel failure can never lose
the notification itself.

Framework-free: the DTO carries plain serialized data across the
boundary; adapters own transport, enrichment (e.g. fresh unread counts),
and tolerance for missing infrastructure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# Event names carried by NotificationEvent. String constants (not an Enum)
# so envelopes serialize naturally across the channel layer.
NOTIFICATION_CREATED = "notification.created"
NOTIFICATION_READ = "notification.read"
NOTIFICATION_ALL_READ = "notification.all_read"


@dataclass(frozen=True)
class NotificationEvent:
    """A notification lifecycle fact heading to a delivery channel.

    ``notification`` is the serialized row (same shape the REST list
    endpoint returns) — present for ``notification.created`` only.
    ``unread_count`` is the recipient's fresh unread total when the
    emitter already knows it; adapters compute it when ``None``.
    """

    event_name: str
    recipient_id: str
    notification_id: str | None = None
    workspace_id: str | None = None
    unread_count: int | None = None
    notification: Mapping[str, Any] | None = field(default=None)


class NotificationChannelPort(ABC):
    """Driven port — deliver one notification event to one channel."""

    @abstractmethod
    def deliver(self, event: NotificationEvent) -> None:
        """Deliver ``event``. Implementations MUST be loss-tolerant:
        a delivery failure is logged, never raised into the caller —
        the in-app row already exists and other channels must still run.
        """
        ...
