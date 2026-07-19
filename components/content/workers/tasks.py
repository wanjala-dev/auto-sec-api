"""Celery tasks for the content bounded context.

PRIMARY ADAPTERS — Celery Beat schedule + on-demand jobs that delegate to
the application layer. The web tier never touches these directly.

Tasks registered:
    content.dispatch_scheduled_newsletters  (Beat — 07:00 UTC daily)
    content.generate_newsletter_draft       (on-demand per workspace+period)
    content.render_newsletter_pdf           (on-demand archive PDF)
    content.render_writing_draft_pdf        (on-demand archive PDF)

The dispatch task NEVER sends newsletters — it produces AI_DRAFTED rows
for human review (per the no-auto-send HARD RULE).
"""

from __future__ import annotations

import datetime
import logging
from typing import Any
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="content.dispatch_scheduled_newsletters",
    bind=True,
    max_retries=2,
    default_retry_delay=600,
    retry_backoff=True,
    retry_jitter=True,
    time_limit=1800,
    soft_time_limit=1620,
)
def dispatch_scheduled_newsletters(self) -> dict[str, int]:
    """Beat entry point — fans out per-workspace newsletter generation.

    Idempotent: ``GenerateNewsletterUseCase`` skips workspaces whose
    newsletter for the current period already exists, so re-running this
    task is safe.
    """

    from components.content.application.providers.writing_provider import (
        WritingProvider,
    )

    logger.info("dispatch_scheduled_newsletters started task_id=%s", self.request.id)

    use_case = WritingProvider().build_dispatch_scheduled_newsletters()
    result = use_case.execute()

    logger.info(
        "dispatch_scheduled_newsletters completed task_id=%s due=%s produced=%s skipped=%s errors=%s",
        self.request.id,
        result.get("due", 0),
        result.get("produced", 0),
        result.get("skipped", 0),
        result.get("errors", 0),
    )
    return result


@shared_task(
    name="content.generate_newsletter_draft",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    retry_backoff=True,
    time_limit=600,
    soft_time_limit=540,
)
def generate_newsletter_draft(
    self,
    workspace_id: str,
    period_start: str,
    period_end: str,
    metrics: dict[str, Any] | None = None,
    user_guidance: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """On-demand "Draft a newsletter for this period" — bypasses the Beat
    schedule. Used by ``POST /api/content/newsletters/generate`` and by
    ad-hoc ops triggers.

    ``period_start`` / ``period_end`` are ISO-format date strings (Celery
    serialises kwargs as JSON; ``datetime.date`` would require eager
    deserialisation hooks).

    ``force=True`` bypasses the (workspace, period) idempotency check
    and overwrites the existing draft in place. Used by the editor's
    "Regenerate" action.
    """

    from components.content.application.providers.writing_provider import (
        WritingProvider,
    )

    use_case = WritingProvider().build_generate_newsletter()
    workspace_uuid = UUID(workspace_id)
    start = datetime.date.fromisoformat(period_start)
    end = datetime.date.fromisoformat(period_end)

    # When no metrics are supplied (the on-demand "Generate" + editor
    # "Regenerate" paths pass none — only the Beat cadence pre-collects them),
    # collect them here so manually generated newsletters are grounded in real
    # workspace data — KPI cards, named highlights, deltas — instead of coming
    # out metric-less and thin. Same collector the scheduled path uses.
    collected_metrics = metrics or {}
    if not collected_metrics:
        from components.content.infrastructure.adapters.newsletter_metrics_collector_adapter import (
            NewsletterMetricsCollectorAdapter,
        )

        collected_metrics = NewsletterMetricsCollectorAdapter().collect(
            workspace_id=workspace_uuid,
            period_start=start,
            period_end=end,
        )

    entity = use_case.execute(
        workspace_id=workspace_uuid,
        period_start=start,
        period_end=end,
        metrics=collected_metrics,
        user_guidance=user_guidance,
        force=force,
    )

    return {
        "newsletter_id": str(entity.id),
        "status": entity.status,
        "title": entity.title,
    }


@shared_task(
    name="content.render_newsletter_pdf",
    bind=True,
    max_retries=4,
    default_retry_delay=30,
    retry_backoff=True,
    time_limit=180,
    soft_time_limit=150,
)
def render_newsletter_pdf(self, newsletter_id: str) -> dict[str, Any]:
    """Render a newsletter's HTML to a PDF archive, store, attach key."""

    from components.content.infrastructure.adapters.email_newsletter_html_render_adapter import (
        EmailNewsletterHtmlRenderAdapter,
    )
    from components.content.infrastructure.adapters.gotenberg_writing_pdf_adapter import (
        GotenbergWritingPdfAdapter,
    )
    from components.content.infrastructure.adapters.writing_pdf_storage_service import (
        WritingPdfStorageService,
    )
    from components.content.infrastructure.repositories.newsletter_read_repository import (
        NewsletterReadRepository,
    )
    from components.content.infrastructure.repositories.newsletter_store_repository import (
        NewsletterStoreRepository,
    )

    reader = NewsletterReadRepository()
    store = NewsletterStoreRepository()
    nl = reader.get(newsletter_id=UUID(newsletter_id))
    if nl is None:
        return {"status": "not_found", "newsletter_id": newsletter_id}

    # Render the canonical block tree to the same email-safe HTML the inbox
    # gets, so the PDF matches the sent newsletter (preview == sent == PDF).
    document_html = EmailNewsletterHtmlRenderAdapter().render(
        layout=(nl.content_payload or {}).get("layout"),
        fallback_html=nl.content_html,
        context={"preheader": nl.preheader},
    )
    pdf_bytes = GotenbergWritingPdfAdapter().render(
        kind="newsletter",
        artifact_id=str(nl.id),
        workspace_id=str(nl.workspace_id),
        title=nl.title,
        body_html=nl.content_html,
        document_html=document_html,
    )
    storage = WritingPdfStorageService()
    key = storage.object_key(
        workspace_id=str(nl.workspace_id),
        kind="newsletter",
        artifact_id=str(nl.id),
    )
    storage.put_pdf(key=key, body=pdf_bytes)
    store.attach_pdf(
        newsletter_id=nl.id,
        pdf_key=key,
        pdf_generated_at=datetime.datetime.now(datetime.UTC),
    )
    return {"status": "ok", "newsletter_id": newsletter_id, "pdf_key": key}


@shared_task(
    name="content.render_writing_draft_pdf",
    bind=True,
    max_retries=4,
    default_retry_delay=30,
    retry_backoff=True,
    time_limit=180,
    soft_time_limit=150,
)
def render_writing_draft_pdf(self, draft_id: str) -> dict[str, Any]:
    """Render a writing draft to a PDF archive, store, attach key."""

    from components.content.infrastructure.adapters.gotenberg_writing_pdf_adapter import (
        GotenbergWritingPdfAdapter,
    )
    from components.content.infrastructure.adapters.writing_pdf_storage_service import (
        WritingPdfStorageService,
    )
    from components.content.infrastructure.repositories.writing_draft_repository import (
        WritingDraftRepository,
    )

    repo = WritingDraftRepository()
    dr = repo.get(draft_id=UUID(draft_id))
    if dr is None:
        return {"status": "not_found", "draft_id": draft_id}

    # Design-template drafts (task #19) carry a block-tree layout in their
    # metadata — render it to the same block HTML the newsletter path uses,
    # so the PDF matches the designed preview (preview == PDF), exactly the
    # newsletter parity rule.
    document_html = None
    layout = (dr.metadata or {}).get("layout")
    if isinstance(layout, dict) and layout.get("blocks"):
        from components.content.infrastructure.adapters.email_newsletter_html_render_adapter import (
            EmailNewsletterHtmlRenderAdapter,
        )

        document_html = EmailNewsletterHtmlRenderAdapter().render(
            layout=layout,
            fallback_html=dr.body_html,
            # A draft's PDF is a document, not an email — no unsubscribe chrome.
            context={"document_only": True},
        )

    pdf_bytes = GotenbergWritingPdfAdapter().render(
        kind=dr.kind,
        artifact_id=str(dr.id),
        workspace_id=str(dr.workspace_id),
        title=dr.title,
        body_html=dr.body_html,
        document_html=document_html,
        # Letter-shaped kinds print this on the letterhead's date line.
        letter_date=dr.updated_at.strftime("%d %B %Y") if dr.updated_at else "",
        # Recipient + signature blocks (task #19) — metadata.letter, same
        # JSON home as the design layout; the adapter treats it as optional
        # and escapes every field.
        letter_fields=(dr.metadata or {}).get("letter"),
    )
    storage = WritingPdfStorageService()
    key = storage.object_key(
        workspace_id=str(dr.workspace_id),
        kind=dr.kind,
        artifact_id=str(dr.id),
    )
    storage.put_pdf(key=key, body=pdf_bytes)
    repo.attach_pdf(
        draft_id=dr.id,
        pdf_key=key,
        pdf_generated_at=datetime.datetime.now(datetime.UTC),
    )
    return {"status": "ok", "draft_id": draft_id, "pdf_key": key}


@shared_task(
    name="content.send_scheduled_newsletters",
    bind=True,
    max_retries=0,  # batch task — re-running on schedule, not via retry
    time_limit=1200,
    soft_time_limit=1080,
)
def send_scheduled_newsletters(self) -> dict[str, int]:
    """Beat entry point (every 5 minutes) — pick up scheduled rows whose
    ``scheduled_for`` time has arrived + dispatch via SendNewsletterUseCase.

    Uses an atomic ``UPDATE WHERE status='scheduled'`` to claim each row
    before dispatch so concurrent runners can't double-send. Failed sends
    flip to ``send_failed`` with a truncated error message — the editor
    UI surfaces those for human review + retry; the batch never
    auto-retries because re-sending a partially-delivered newsletter
    would double-message early recipients.

    Returns ``{"claimed": N, "sent": N, "failed": N, "skipped": N}`` for
    operator visibility in the worker logs.
    """

    from django.utils import timezone

    from components.content.application.providers.writing_provider import (
        WritingProvider,
    )

    use_case = WritingProvider().build_dispatch_due_scheduled_newsletters()
    summary = use_case.execute(now=timezone.now(), system_user_id=0)
    logger.info(
        "send_scheduled_newsletters_summary claimed=%d sent=%d failed=%d skipped=%d",
        summary["claimed"],
        summary["sent"],
        summary["failed"],
        summary["skipped"],
    )
    return summary


@shared_task(
    name="content.send_subscription_confirmation_email",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_jitter=True,
)
def send_subscription_confirmation_email(
    self,
    *,
    workspace_id: str,
    email: str,
    token: str,
) -> dict[str, str]:
    """Dispatch the double-opt-in confirmation email.

    Fires off the public subscribe path when the workspace has
    ``double_opt_in_enabled=True``. The email contains a single CTA
    pointing at ``FRONTEND_URL/c/<token>`` which the FE landing page
    POSTs to ``/content/public/confirm/<token>/``.

    Idempotent at the SES + subscriber side: re-sending the same
    confirmation email after a Celery retry is harmless (the FE landing
    page short-circuits on already-confirmed tokens).
    """

    from django.conf import settings
    from django.core.mail import EmailMultiAlternatives

    from infrastructure.persistence.workspaces.models import Workspace

    workspace = Workspace.objects.filter(id=workspace_id).first()
    workspace_name = workspace.name if workspace else "this workspace"

    frontend = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    confirm_url = f"{frontend}/c/{token}" if frontend else f"/c/{token}"

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "info@octopusintl.org")
    subject = f"Confirm your subscription to {workspace_name}"
    plain_body = (
        f"Hi,\n\n"
        f"Please confirm you want to receive newsletters from "
        f"{workspace_name} by clicking the link below:\n\n"
        f"{confirm_url}\n\n"
        f"If you did not request this, you can safely ignore this email.\n"
    )
    html_body = (
        f"<p>Please confirm you want to receive newsletters from "
        f"<strong>{workspace_name}</strong>.</p>"
        f'<p><a href="{confirm_url}" '
        f'style="background:#1f2937;color:#fff;padding:10px 16px;'
        f'border-radius:6px;text-decoration:none;">Confirm subscription</a></p>'
        f'<p style="font-size:12px;color:#666;">If you did not request '
        f"this, you can safely ignore this email.</p>"
    )

    message = EmailMultiAlternatives(
        subject=subject,
        body=plain_body,
        from_email=from_email,
        to=[email],
    )
    message.attach_alternative(html_body, "text/html")
    try:
        message.send(fail_silently=False)
    except Exception as exc:
        logger.exception(
            "send_subscription_confirmation_email_failed token=%s",
            token,
        )
        raise self.retry(exc=exc) from exc

    logger.info(
        "send_subscription_confirmation_email_dispatched workspace_id=%s token=%s",
        workspace_id,
        token,
    )
    return {"status": "dispatched"}
