"""Port: tell recipients something was shared with them (task #21).

When a chat message carries a ``metadata.share`` card, the recipients
should hear about it outside the thread too — an in-app notification and
an email ("<sender> shared “<title>” with you"). The adapter is
failure-safe decoration: a notification/email failure never fails the
message send.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


class ShareNotificationPort(Protocol):
    def notify_share(
        self,
        *,
        sender_id: UUID,
        recipient_user_ids: Sequence[UUID],
        share: dict,
        workspace_id: UUID | None = None,
    ) -> None: ...
