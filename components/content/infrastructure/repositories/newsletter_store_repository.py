"""ORM-backed Newsletter writes."""

from __future__ import annotations

import datetime
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from components.content.application.ports.newsletter_store_port import (
    NewsletterStorePort,
)
from components.content.domain.entities.newsletter_entity import NewsletterEntity
from components.content.domain.enums import NewsletterStatus
from components.content.domain.errors import (
    NewsletterAlreadySentError,
    NewsletterNotFoundError,
)


def _to_entity(row) -> NewsletterEntity:
    return NewsletterEntity(
        id=row.id,
        workspace_id=row.workspace_id,
        title=row.title,
        content_html=row.content_html,
        status=row.status,
        scheduled_for=row.scheduled_for,
        sent_at=row.sent_at,
        pdf_key=row.pdf_key or "",
        pdf_generated_at=row.pdf_generated_at,
        author_id=row.author_id,
        ai_drafted_by_agent=row.ai_drafted_by_agent or "",
        period_start=row.period_start,
        period_end=row.period_end,
        content_payload=dict(row.content_payload or {}),
        metadata=dict(row.metadata or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
        # Pre-send guardrail fields (added 2026-06-11 in migration 0006).
        # ``getattr`` with default keeps the mapper safe against rows
        # loaded from older migrations during the rollout window.
        subject=getattr(row, "subject", "") or "",
        preheader=getattr(row, "preheader", "") or "",
        from_name=getattr(row, "from_name", "") or "",
        reply_to=getattr(row, "reply_to", "") or "",
        # Send metrics (task #25, migration 0021).
        recipient_count=getattr(row, "recipient_count", None),
        failed_count=getattr(row, "failed_count", None),
        unique_open_count=getattr(row, "unique_open_count", 0) or 0,
        total_open_count=getattr(row, "total_open_count", 0) or 0,
        last_opened_at=getattr(row, "last_opened_at", None),
    )


class NewsletterStoreRepository(NewsletterStorePort):
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
    ) -> NewsletterEntity:
        from infrastructure.persistence.content.models import Newsletter

        NewsletterStatus.validate(status)
        row = Newsletter.objects.create(
            workspace_id=workspace_id,
            title=title,
            content_html=content_html,
            status=status,
            author_id=author_id,
            ai_drafted_by_agent=ai_drafted_by_agent,
            period_start=period_start,
            period_end=period_end,
            content_payload=content_payload or {},
            metadata=metadata or {},
        )
        if subscriber_ids:
            row.subscribers.set(list(subscriber_ids))
        return _to_entity(row)

    def merge_metadata_key(self, *, newsletter_id: UUID, key: str, value: dict) -> None:
        from infrastructure.persistence.content.models import Newsletter

        try:
            row = Newsletter.objects.get(pk=newsletter_id)
        except Newsletter.DoesNotExist as exc:
            raise NewsletterNotFoundError(str(newsletter_id)) from exc
        metadata = dict(row.metadata or {})
        metadata[key] = value
        row.metadata = metadata
        row.save(update_fields=["metadata", "updated_at"])

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
        layout: dict | None = None,
    ) -> NewsletterEntity:
        """Update editor-side fields. None means "leave the column alone";
        empty string is a legitimate "clear this override" value. ``layout``
        (a block tree) replaces content_payload['layout'] — the AI-completed
        design becomes the latest version (task: AI assist edits the design,
        not just the fallback body)."""

        from infrastructure.persistence.content.models import Newsletter

        try:
            row = Newsletter.objects.get(pk=newsletter_id)
        except Newsletter.DoesNotExist as exc:
            raise NewsletterNotFoundError(str(newsletter_id)) from exc
        update_fields = ["title", "content_html", "updated_at"]
        row.title = title
        row.content_html = content_html
        if isinstance(layout, dict) and layout.get("blocks"):
            payload = dict(row.content_payload or {})
            payload["layout"] = layout
            row.content_payload = payload
            update_fields.append("content_payload")
        if subject is not None:
            row.subject = subject
            update_fields.append("subject")
        if preheader is not None:
            row.preheader = preheader
            update_fields.append("preheader")
        if from_name is not None:
            row.from_name = from_name
            update_fields.append("from_name")
        if reply_to is not None:
            row.reply_to = reply_to
            update_fields.append("reply_to")
        row.save(update_fields=update_fields)
        return _to_entity(row)

    def replace_ai_draft(
        self,
        *,
        newsletter_id: UUID,
        title: str,
        content_html: str,
        content_payload: dict[str, Any],
        ai_drafted_by_agent: str,
    ) -> NewsletterEntity:
        from infrastructure.persistence.content.models import Newsletter

        try:
            row = Newsletter.objects.get(pk=newsletter_id)
        except Newsletter.DoesNotExist as exc:
            raise NewsletterNotFoundError(str(newsletter_id)) from exc
        if row.status == NewsletterStatus.SENT:
            raise NewsletterAlreadySentError(str(newsletter_id))
        row.title = title
        row.content_html = content_html
        row.content_payload = content_payload or {}
        row.ai_drafted_by_agent = ai_drafted_by_agent or ""
        # Reset status back to ``ai_drafted`` so reviewers see the
        # refreshed draft on the Newsletters list. Anything that was
        # scheduled gets unscheduled — the human has to re-review the
        # regenerated content before sending.
        row.status = NewsletterStatus.AI_DRAFTED
        row.scheduled_for = None
        row.save(
            update_fields=[
                "title",
                "content_html",
                "content_payload",
                "ai_drafted_by_agent",
                "status",
                "scheduled_for",
                "updated_at",
            ]
        )
        return _to_entity(row)

    def mark_scheduled(
        self,
        *,
        newsletter_id: UUID,
        scheduled_for: datetime.datetime,
    ) -> NewsletterEntity:
        from infrastructure.persistence.content.models import Newsletter

        try:
            row = Newsletter.objects.get(pk=newsletter_id)
        except Newsletter.DoesNotExist as exc:
            raise NewsletterNotFoundError(str(newsletter_id)) from exc
        if row.status == NewsletterStatus.SENT:
            raise NewsletterAlreadySentError(str(newsletter_id))
        row.status = NewsletterStatus.SCHEDULED
        row.scheduled_for = scheduled_for
        row.save(update_fields=["status", "scheduled_for", "updated_at"])
        return _to_entity(row)

    def mark_sent(
        self,
        *,
        newsletter_id: UUID,
        sent_at: datetime.datetime,
    ) -> NewsletterEntity:
        """Flip status to SENT. ONLY the human-action SendNewsletterUseCase
        may call this — see ``components.content.application.use_cases.
        send_newsletter_use_case`` for the policy enforcement."""
        from infrastructure.persistence.content.models import Newsletter

        try:
            row = Newsletter.objects.get(pk=newsletter_id)
        except Newsletter.DoesNotExist as exc:
            raise NewsletterNotFoundError(str(newsletter_id)) from exc
        if row.status == NewsletterStatus.SENT:
            raise NewsletterAlreadySentError(str(newsletter_id))
        row.status = NewsletterStatus.SENT
        row.sent_at = sent_at
        row.save(update_fields=["status", "sent_at", "updated_at"])
        return _to_entity(row)

    def try_claim_scheduled_for_send(
        self,
        *,
        newsletter_id: UUID,
        now: datetime.datetime,
    ) -> bool:
        from infrastructure.persistence.content.models import Newsletter

        # Single atomic UPDATE — concurrent batch runners can't both win.
        # ``scheduled_for__lte=now`` keeps rows whose time hasn't arrived
        # from being claimed early.
        rows = Newsletter.objects.filter(
            pk=newsletter_id,
            status=NewsletterStatus.SCHEDULED,
            scheduled_for__lte=now,
        ).update(status=NewsletterStatus.SENDING)
        return rows > 0

    def mark_send_failed(
        self,
        *,
        newsletter_id: UUID,
        error_message: str,
    ) -> NewsletterEntity:
        from infrastructure.persistence.content.models import Newsletter

        try:
            row = Newsletter.objects.get(pk=newsletter_id)
        except Newsletter.DoesNotExist as exc:
            raise NewsletterNotFoundError(str(newsletter_id)) from exc
        row.status = NewsletterStatus.SEND_FAILED
        metadata = dict(row.metadata or {})
        # Truncate to keep the JSON payload small; full traceback is in
        # logs anyway. UI surfaces the truncated message inline.
        metadata["last_error"] = (error_message or "")[:1024]
        row.metadata = metadata
        row.save(update_fields=["status", "metadata", "updated_at"])
        return _to_entity(row)

    def attach_pdf(
        self,
        *,
        newsletter_id: UUID,
        pdf_key: str,
        pdf_generated_at: datetime.datetime,
    ) -> NewsletterEntity:
        from infrastructure.persistence.content.models import Newsletter

        try:
            row = Newsletter.objects.get(pk=newsletter_id)
        except Newsletter.DoesNotExist as exc:
            raise NewsletterNotFoundError(str(newsletter_id)) from exc
        row.pdf_key = pdf_key
        row.pdf_generated_at = pdf_generated_at
        row.save(update_fields=["pdf_key", "pdf_generated_at", "updated_at"])
        return _to_entity(row)

    def archive(self, *, newsletter_id: UUID) -> NewsletterEntity:
        from infrastructure.persistence.content.models import Newsletter

        try:
            row = Newsletter.objects.get(pk=newsletter_id)
        except Newsletter.DoesNotExist as exc:
            raise NewsletterNotFoundError(str(newsletter_id)) from exc
        row.status = NewsletterStatus.ARCHIVED
        row.save(update_fields=["status", "updated_at"])
        return _to_entity(row)
