"""Port: tell conversation participants a new direct message arrived.

The in-app bell is the only leg here — the thread itself is the primary
surface, so no email. The adapter is failure-safe decoration: a
notification failure never fails the message send.

Mute + self-exclusion are the USE CASE's job (domain state lives on the
conversation aggregate); the adapter only fans out to the ids it is
given via the canonical dispatcher funnel (which adds preference
filtering + the 5-minute dedup window so message bursts collapse into
one row per conversation).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID


class MessageNotificationPort(Protocol):
    def notify_new_message(
        self,
        *,
        sender_id: UUID,
        recipient_user_ids: Sequence[UUID],
        conversation_id: UUID,
        workspace_id: UUID | None = None,
        preview: str = "",
    ) -> None: ...
