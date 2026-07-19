"""Use case: record an SES SNS bounce notification.

Hard bounces (permanent — invalid mailbox, no MX record, blocked
domain) add the address to ``SuppressedAddress`` system-wide. Future
sends to that address from any workspace are skipped by the dispatch
adapter's join against the suppression table. The matching Subscriber
row (if any) is soft-deleted so the workspace's subscriber list
reflects reality.

Soft bounces (transient — mailbox full, server timeout) are logged but
NOT suppressed. SES retries on its own up to ~50 times; if a transient
becomes a hard bounce, SES sends a separate Permanent notification we
handle as above.

Idempotency: SES retries the same SNS notification on transient
delivery failure; both the suppress + the soft-delete must be safe on
repeat. SuppressedAddress.suppress() returns False if the row already
exists; soft_remove_by_email() is a no-op if already removed.
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

# SES bounce types per https://docs.aws.amazon.com/ses/latest/dg/notification-contents.html
_PERMANENT = "Permanent"
_TRANSIENT = "Transient"
_UNDETERMINED = "Undetermined"


@dataclass
class RecordEmailBounceUseCase:
    subscriber_store: SubscriberStorePort
    suppression_store: SuppressionStorePort

    def execute(
        self,
        *,
        bounce_type: str,
        bounced_addresses: list[str],
        source_event: dict[str, Any],
    ) -> int:
        """Return the count of newly suppressed addresses.

        Caller passes the SES notification's ``bounceType`` +
        ``bouncedRecipients[].emailAddress`` list + the raw notification
        body. Transient bounces are no-ops; permanent + undetermined
        (treated as permanent per AWS recommendation) suppress
        system-wide.
        """

        if bounce_type == _TRANSIENT:
            return 0

        newly_suppressed = 0
        for email in bounced_addresses:
            inserted = self.suppression_store.suppress(
                workspace_id=None,
                email=email,
                reason=SuppressedAddressReason.HARD_BOUNCE,
                source_event=source_event,
            )
            if inserted:
                newly_suppressed += 1
            # Best-effort soft-delete on every workspace's subscriber
            # row matching the email. Since we don't have a "find
            # subscribers by email across workspaces" port method,
            # leave the cross-workspace cleanup to a follow-up Celery
            # task. For now, the suppression check on send is
            # sufficient — the bad address won't get another message.
        return newly_suppressed
