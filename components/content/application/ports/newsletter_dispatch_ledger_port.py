"""Port for the per-recipient email dispatch ledger (task #25 — send metrics).

The ledger is the persistence half of send tracking: one record per
recipient, issued BEFORE dispatch (each record's ``open_token`` keys the
tracking pixel embedded in that recipient's email), finalized after with
per-recipient outcomes, and incremented by the public open-pixel endpoint.

Open-rate honesty note: pixel opens are the industry-standard measure and
carry the industry-standard caveats (image-blocking undercounts, mail-
privacy prefetchers overcount). The UI labels them "opens", not "readers".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID


class NewsletterDispatchLedgerPort(ABC):
    @abstractmethod
    def issue(
        self,
        *,
        workspace_id: UUID,
        newsletter_id: UUID,
        emails: Sequence[str],
    ) -> dict[str, str]:
        """Create pending dispatch records for the recipients and return
        ``{email: open_token}`` for pixel injection."""

    @abstractmethod
    def finalize(
        self,
        *,
        newsletter_id: UUID,
        delivered_emails: Sequence[str],
        failed_emails: Sequence[str],
    ) -> None:
        """Mark each record sent/failed and write the newsletter's
        denormalized counters (recipient_count / failed_count)."""

    @abstractmethod
    def record_open(self, *, open_token: UUID) -> bool:
        """Count an open for the recipient behind ``open_token`` —
        increments the record (first/last opened, open_count) and the
        artifact's denormalized counters (total always; unique only on
        the recipient's first open). Returns False for unknown tokens."""
