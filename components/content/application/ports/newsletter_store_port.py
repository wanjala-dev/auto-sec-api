"""Port for Newsletter persistence writes."""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from typing import Any, Protocol
from uuid import UUID

from components.content.domain.entities.newsletter_entity import NewsletterEntity


class NewsletterStorePort(Protocol):
    def create(
        self,
        *,
        workspace_id: UUID,
        title: str,
        content_html: str,
        status: str,
        author_id: int | None = None,
        ai_drafted_by_agent: str = "",
        period_start: datetime.date | None = None,
        period_end: datetime.date | None = None,
        content_payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        subscriber_ids: Iterable[int] | None = None,
    ) -> NewsletterEntity: ...

    def merge_metadata_key(self, *, newsletter_id: UUID, key: str, value: dict) -> None:
        """Atomically set ONE metadata key without touching the rest of
        the document — server-written keys (``ai_provenance``) use this."""
        ...

    def update_body(
        self,
        *,
        newsletter_id: UUID,
        title: str,
        content_html: str,
        subject: str | None = None,
        preheader: str | None = None,
        from_name: str | None = None,
        reply_to: str | None = None,
    ) -> NewsletterEntity: ...

    def replace_ai_draft(
        self,
        *,
        newsletter_id: UUID,
        title: str,
        content_html: str,
        content_payload: dict[str, Any],
        ai_drafted_by_agent: str,
    ) -> NewsletterEntity:
        """Replace the AI-generated body of an existing draft.

        Used by ``GenerateNewsletterUseCase`` when ``force=True`` —
        re-runs the writing_agent on the same workspace + period and
        overwrites the existing draft in place. Refuses if the
        newsletter has already been sent (audit trail is preserved).
        The newsletter UUID stays the same so existing links resolve.
        """
        ...

    def mark_scheduled(
        self,
        *,
        newsletter_id: UUID,
        scheduled_for: datetime.datetime,
    ) -> NewsletterEntity: ...

    def mark_sent(
        self,
        *,
        newsletter_id: UUID,
        sent_at: datetime.datetime,
    ) -> NewsletterEntity:
        """Flip status to SENT. ONLY the human-action SendNewsletterUseCase
        may invoke this. Cadence/AI code paths must not call mark_sent."""
        ...

    def try_claim_scheduled_for_send(
        self,
        *,
        newsletter_id: UUID,
        now: datetime.datetime,
    ) -> bool:
        """Atomic CAS: flip status SCHEDULED → SENDING iff scheduled_for<=now.

        Returns True if this caller claimed the row (its batch task should
        proceed with dispatch). Returns False if another worker beat us
        to it, or the row is not in SCHEDULED state, or its scheduled_for
        is still in the future. The caller MUST NOT proceed with the
        dispatch on False — the row may already be in flight.

        Implemented via a single ``UPDATE … WHERE status='scheduled'``
        so concurrent batch runners can't both pick the same row.
        """
        ...

    def mark_send_failed(
        self,
        *,
        newsletter_id: UUID,
        error_message: str,
    ) -> NewsletterEntity:
        """Flip status to SEND_FAILED + stash the error on metadata.

        Surface for operators in the editor UI; the batch task does NOT
        auto-retry SEND_FAILED rows — re-sending a partially-delivered
        newsletter would double-message early recipients."""
        ...

    def attach_pdf(
        self,
        *,
        newsletter_id: UUID,
        pdf_key: str,
        pdf_generated_at: datetime.datetime,
    ) -> NewsletterEntity: ...

    def archive(self, *, newsletter_id: UUID) -> NewsletterEntity: ...
