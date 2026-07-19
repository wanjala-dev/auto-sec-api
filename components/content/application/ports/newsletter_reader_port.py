"""Port for Newsletter reads."""

from __future__ import annotations

import datetime
from typing import Protocol, Sequence
from uuid import UUID

from components.content.domain.entities.newsletter_entity import NewsletterEntity
from components.content.domain.value_objects.subscriber_dispatch_target import (
    SubscriberDispatchTarget,
)


class NewsletterReaderPort(Protocol):
    def get(self, *, newsletter_id: UUID) -> NewsletterEntity | None: ...

    def list_for_workspace(
        self,
        *,
        workspace_id: UUID,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[NewsletterEntity]: ...

    def find_for_period(
        self,
        *,
        workspace_id: UUID,
        period_start: datetime.date,
        period_end: datetime.date,
    ) -> NewsletterEntity | None:
        """Return the existing cadence-driven newsletter row for the given
        period, or None. Used by the dispatch task to enforce idempotency
        on ``(workspace, range_start, range_end)``."""
        ...

    def count_workspace_dispatch_targets(
        self,
        *,
        workspace_id: UUID,
    ) -> int:
        """Return the count returned by ``list_workspace_dispatch_targets``
        without materialising the rows. Used by the editor's pre-send
        confirm modal to show "Send to N people"."""
        ...

    def list_workspace_dispatch_targets(
        self,
        *,
        workspace_id: UUID,
    ) -> Sequence[SubscriberDispatchTarget]:
        """Return the workspace's send-eligible subscribers.

        Filters applied:
        - ``is_active=True`` (excludes unsubscribed rows even when
          they're still in the M2M because they were on the list at
          draft time).
        - Email NOT in ``SuppressedAddress`` (workspace-scoped OR
          system-wide). Suppression wins over membership — a complainer
          stays blocked even if an admin re-adds them.

        The newsletter's M2M ``subscribers`` is preserved as an audit
        trail of "who was on the list when this draft was created", but
        the actual send recipients are recomputed here at send time so
        unsubscribes between draft creation and send are respected.
        """
        ...

    def count_dispatch_targets_for_emails(
        self,
        *,
        workspace_id: UUID,
        emails: Sequence[str],
    ) -> int:
        """Return how many of ``emails`` are send-eligible subscribers.

        Same filters as ``list_dispatch_targets_for_emails`` but count-only —
        used by the contacts segment-send preview to show "N of M contacts
        are subscribed and will receive this" before the admin commits.
        """
        ...

    def list_dispatch_targets_for_emails(
        self,
        *,
        workspace_id: UUID,
        emails: Sequence[str],
    ) -> Sequence[SubscriberDispatchTarget]:
        """Return the dispatch targets for the subset of ``emails`` that are
        send-eligible subscribers in this workspace.

        Identical filtering to ``list_workspace_dispatch_targets`` (active +
        not suppressed) but restricted to the given address list. Addresses
        that are NOT active, non-suppressed subscribers — never-subscribed
        contacts, unsubscribed rows, suppressed (bounced/complained)
        addresses — are dropped. This is what keeps a segment send strictly
        to people who already consented to the newsletter.
        """
        ...

    # Legacy: returns plain email strings from the newsletter's M2M.
    # Kept transiently so existing call sites (none in production after
    # 2026-06-11 — verified by grep) don't break during the dispatch
    # rewrite landing. Mark for removal once the next baseline shows
    # zero callers.
    def list_subscriber_emails(
        self,
        *,
        newsletter_id: UUID,
    ) -> Sequence[str]: ...
