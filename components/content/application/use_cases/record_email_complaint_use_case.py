"""Use case: record an SES SNS complaint notification.

A complaint is the subscriber clicking "report spam" in their inbox.
Treat as a strong unsubscribe signal — system-wide suppression + soft
removal of the matching Subscriber row. Complaint rates above 0.1%
trigger SES reputation damage; aggressively suppressing complained
addresses is how we stay under that ceiling.

Idempotent on repeat SNS delivery same as the bounce handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from components.content.application.ports.subscriber_store_port import (
    SubscriberStorePort,
)
from components.content.application.ports.suppression_store_port import (
    SuppressionStorePort,
)
from components.content.domain.enums import SuppressedAddressReason


@dataclass
class RecordEmailComplaintUseCase:
    subscriber_store: SubscriberStorePort
    suppression_store: SuppressionStorePort

    def execute(
        self,
        *,
        complained_addresses: list[str],
        source_event: dict[str, Any],
    ) -> int:
        newly_suppressed = 0
        for email in complained_addresses:
            inserted = self.suppression_store.suppress(
                workspace_id=None,
                email=email,
                reason=SuppressedAddressReason.COMPLAINT,
                source_event=source_event,
            )
            if inserted:
                newly_suppressed += 1
        return newly_suppressed
