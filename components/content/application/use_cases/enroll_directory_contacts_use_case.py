"""Use case: enroll directory contacts onto the workspace newsletter list.

The deliberate "add these contacts to my newsletter list" admin action. Each
recipient is created as an active subscriber (source=directory_picked) IF AND
ONLY IF no subscriber row already exists for that address — an existing row,
active or unsubscribed, is left untouched, so a prior opt-out is never
resurrected (CAN-SPAM: once someone unsubscribes you must honour it, even on an
explicit admin re-add).

Returns a per-batch tally so the caller can report "added N, M already on the
list, K skipped because they unsubscribed". The contacts segment-subscribe
endpoint orchestrates this from its own segment membership.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from components.content.application.ports.subscriber_store_port import (
    SubscriberStorePort,
)


@dataclass
class EnrollDirectoryContactsResult:
    added: int = 0
    already_subscribed: int = 0
    skipped_unsubscribed: int = 0


@dataclass
class EnrollDirectoryContactsUseCase:
    subscriber_store: SubscriberStorePort

    def execute(
        self,
        *,
        workspace_id: UUID,
        recipients: Sequence[tuple[str, str]],
    ) -> EnrollDirectoryContactsResult:
        """``recipients`` is a sequence of ``(email, name)`` pairs."""
        result = EnrollDirectoryContactsResult()
        for email, name in recipients:
            outcome = self.subscriber_store.enroll_from_directory(
                workspace_id=workspace_id,
                email=email,
                name=name or "",
            )
            if outcome == "added":
                result.added += 1
            elif outcome == "skipped_unsubscribed":
                result.skipped_unsubscribed += 1
            else:
                result.already_subscribed += 1
        return result
