"""Use case: HUMAN-TRIGGERED newsletter send.

This is the ONLY code path that may flip a Newsletter's status to SENT.
Cadence / AI / scheduled-dispatch paths must produce only AI_DRAFTED rows;
the human reviews in the Writing UI and explicitly invokes this use case
via the ``POST /api/content/newsletters/<id>/send`` action endpoint.

The send path:
  1. Load the newsletter; refuse if already sent.
  2. Pull workspace-scoped active dispatch targets (excludes
     unsubscribed + suppressed addresses).
  3. Call the dispatch port — per-recipient send with RFC 8058
     List-Unsubscribe headers + tokenized footer. Whole-batch transport
     failures raise; per-recipient failures are logged + counted.
  4. mark_sent() on the store port (which also raises if status==SENT —
     belt and suspenders against races).
  5. Emit NewsletterSent domain event with the delivered count, not the
     attempted count.

The newsletter's subject/from_name/reply_to/preheader overrides flow
through here when set; defaults from the workspace preference apply
when blank.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

logger = logging.getLogger(__name__)

from components.shared_kernel.application.ports.settings_port import (
    SettingsPort,
)


def _settings() -> SettingsPort:
    """Return the default Django-backed settings adapter.

    Lazy import keeps the application layer's import graph clean.
    Override in tests by monkeypatching this function.
    """
    from components.shared_kernel.infrastructure.adapters.django_settings_adapter import (
        DjangoSettingsAdapter,
    )

    return DjangoSettingsAdapter()


from components.content.application.ports.faithfulness_check_port import (
    FaithfulnessCheckPort,
)
from components.content.application.ports.newsletter_dispatch_ledger_port import (
    NewsletterDispatchLedgerPort,
)
from components.content.application.ports.newsletter_dispatch_port import (
    NewsletterDispatchPort,
)
from components.content.application.ports.newsletter_html_render_port import (
    NewsletterHtmlRenderPort,
)
from components.content.application.ports.newsletter_reader_port import (
    NewsletterReaderPort,
)
from components.content.application.ports.newsletter_store_port import (
    NewsletterStorePort,
)
from components.content.application.use_cases.faithfulness_gate import (
    enforce_faithfulness_gate,
)
from components.content.domain.entities.newsletter_entity import NewsletterEntity
from components.content.domain.enums import NewsletterStatus
from components.content.domain.errors import (
    NewsletterAlreadySentError,
    NewsletterNotFoundError,
)
from components.content.domain.events.newsletter_sent_event import (
    NewsletterSent,
)
from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
    CeleryEventPublisher,
)


@dataclass
class SendNewsletterUseCase:
    newsletter_store: NewsletterStorePort
    newsletter_reader: NewsletterReaderPort
    newsletter_dispatch: NewsletterDispatchPort
    newsletter_html_render: NewsletterHtmlRenderPort
    event_publisher: CeleryEventPublisher
    # Optional so existing constructions (and tests) keep working; the
    # provider wires the real checker. When unset, the faithfulness gate
    # is a no-op.
    faithfulness_check: FaithfulnessCheckPort | None = None
    # Optional per-recipient dispatch ledger (task #25 — send metrics).
    # When wired, every recipient gets a tracked record + open pixel and
    # the newsletter's denormalized counters are written at send time.
    dispatch_ledger: NewsletterDispatchLedgerPort | None = None

    def execute(
        self,
        *,
        newsletter_id: UUID,
        triggered_by_user_id: int,
        now: datetime.datetime,
        recipient_emails: Sequence[str] | None = None,
        expected_workspace_id: UUID | None = None,
        override_unverified: bool = False,
    ) -> NewsletterEntity:
        """Send the newsletter and flip it to SENT.

        ``recipient_emails`` narrows the audience to a specific subset of the
        workspace's send-eligible subscribers (the segment-send path) — only
        addresses that are already active, non-suppressed subscribers receive
        it; non-subscribers in the list are silently dropped by the reader's
        suppression-aware subset query. When ``None`` the whole workspace's
        eligible subscribers are used (the standard send).

        ``expected_workspace_id`` is a cross-context safety guard: when a
        caller in another bounded context (contacts) triggers a send, it
        passes the workspace it scoped its recipients to; if the newsletter
        belongs to a different workspace we treat it as not-found rather than
        sending one workspace's newsletter to another's subscribers.
        """
        current = self.newsletter_reader.get(newsletter_id=newsletter_id)
        if current is None:
            raise NewsletterNotFoundError(str(newsletter_id))
        if expected_workspace_id is not None and current.workspace_id != expected_workspace_id:
            raise NewsletterNotFoundError(str(newsletter_id))
        if current.status == NewsletterStatus.SENT:
            raise NewsletterAlreadySentError(str(newsletter_id))

        if recipient_emails is None:
            targets = self.newsletter_reader.list_workspace_dispatch_targets(workspace_id=current.workspace_id)
        else:
            targets = self.newsletter_reader.list_dispatch_targets_for_emails(
                workspace_id=current.workspace_id,
                emails=recipient_emails,
            )

        # No active, non-suppressed subscribers — refuse rather than
        # silently mark sent. A workspace with zero send-eligible
        # subscribers should add some first.
        if not targets:
            raise NewsletterAlreadySentError(f"Newsletter {newsletter_id} has no eligible subscribers; aborting send.")

        # Subject + From + Reply-To resolution: prefer per-row overrides,
        # fall back to workspace preference defaults, fall back to
        # platform defaults. Platform defaults live in settings —
        # ``EMAIL_FROM`` (info@octopusintl.org) + ``EMAIL_FROM_NAME_TEMPLATE``.
        subject = (current.subject or current.title).strip()
        # The use case doesn't know the workspace's display name without
        # an extra query; the adapter handles the fallback when
        # sender_name is None.
        sender_name = (current.from_name or "").strip() or None
        reply_to = (current.reply_to or "").strip() or None

        # Unsubscribe URLs point at the frontend landing page so
        # subscribers see a branded "you're unsubscribed" screen rather
        # than a bare API response. The landing page POSTs the token to
        # the public unsubscribe endpoint.
        settings = _settings()
        frontend_url = settings.get("FRONTEND_URL", "").rstrip("/")
        list_unsubscribe_base_url = f"{frontend_url}/u/" if frontend_url else "/u/"
        list_unsubscribe_mailto = settings.get("EMAIL_UNSUBSCRIBE_MAILTO", "unsubscribe@octopusintl.org")

        # Render the canonical block tree to email-safe HTML so the inbox gets
        # the designed newsletter — not the bare ``content_html`` prose. Falls
        # back to ``content_html`` for legacy rows with no ``layout``. The
        # ``{{unsubscribe_url}}`` token in the rendered footer is substituted
        # per recipient by the dispatch adapter.
        html_body = self.newsletter_html_render.render(
            layout=(current.content_payload or {}).get("layout"),
            fallback_html=current.content_html,
            context={"preheader": current.preheader},
        )

        # Faithfulness gate: never email donors a figure the newsletter's
        # own data can't support. Verifies the rendered body (pre dispatch
        # chrome) against the persisted metrics corpus; blocks unless the
        # operator explicitly overrides. Raises NewsletterUnverifiedFiguresError.
        enforce_faithfulness_gate(
            faithfulness_check=self.faithfulness_check,
            newsletter=current,
            html_body=html_body,
            override_unverified=override_unverified,
        )

        # Issue per-recipient dispatch records BEFORE sending — each
        # record's open token keys the tracking pixel embedded in that
        # recipient's copy (task #25).
        open_tokens: dict[str, str] = {}
        if self.dispatch_ledger is not None:
            open_tokens = self.dispatch_ledger.issue(
                workspace_id=current.workspace_id,
                newsletter_id=newsletter_id,
                emails=[t.email for t in targets],
            )

        summary = self.newsletter_dispatch.send(
            subject=subject,
            html_body=html_body,
            plain_body="",  # adapter computes plain fallback from HTML
            targets=targets,
            sender_name=sender_name,
            reply_to=reply_to,
            list_unsubscribe_base_url=list_unsubscribe_base_url,
            list_unsubscribe_mailto=list_unsubscribe_mailto,
            open_tokens=open_tokens or None,
        )

        if self.dispatch_ledger is not None:
            self.dispatch_ledger.finalize(
                newsletter_id=newsletter_id,
                delivered_emails=summary.delivered_emails,
                failed_emails=summary.failed_emails,
            )

        sent = self.newsletter_store.mark_sent(
            newsletter_id=newsletter_id,
            sent_at=now,
        )

        self.event_publisher.publish(
            NewsletterSent(
                workspace_id=sent.workspace_id,
                newsletter_id=sent.id,
                title=sent.title,
                triggered_by_user_id=triggered_by_user_id,
                sent_at=now,
                subscriber_count=summary.delivered,
            )
        )

        # Fire the ``email_sent`` workflow trigger once per recipient contact.
        # "Contact receives an email" is inherently per-recipient — that IS the
        # design — so this fans out one outbox row + one after-commit task per
        # subscriber. The fan-out is bounded by the eligible-subscriber count
        # (``targets``), and each emit only writes a row + schedules a task; the
        # dispatcher cheaply drops events for which no active ``email_sent``
        # binding exists. Recipients are newsletter subscribers (not
        # WorkspaceMembership directory rows), so each run targets the subscriber
        # by email — there is no user id, hence ``contact_id`` is empty.
        self._emit_email_sent_per_recipient(
            workspace_id=sent.workspace_id,
            newsletter_id=sent.id,
            targets=targets,
        )
        return sent

    @staticmethod
    def _emit_email_sent_per_recipient(
        *,
        workspace_id,
        newsletter_id,
        targets,
    ) -> None:
        """Emit one ``email_sent`` workflow event per recipient subscriber."""
        try:
            from components.workflow.application.providers.workflow_dispatcher_provider import (
                get_workflow_dispatcher_provider,
            )
        except Exception:
            logger.exception(
                "Failed to load workflow dispatcher for email_sent newsletter_id=%s",
                newsletter_id,
            )
            return

        emit_workflow_event = get_workflow_dispatcher_provider().emit_workflow_event
        emitted = 0
        for target in targets:
            email = (getattr(target, "email", "") or "").strip()
            if not email:
                continue
            try:
                emit_workflow_event(
                    workspace_id=str(workspace_id),
                    source_type="communication",
                    trigger_type="email_sent",
                    payload={
                        "workspace_id": str(workspace_id),
                        "newsletter_id": str(newsletter_id),
                        "target_type": "contact",
                        "target_id": email,
                        "contact_id": "",
                        "subscriber_email": email,
                        "subscriber_name": getattr(target, "name", "") or "",
                    },
                    source_id=str(newsletter_id),
                    idempotency_key=f"email_sent:{newsletter_id}:{email}",
                )
                emitted += 1
            except Exception:
                # Per-recipient log-and-continue: one bad emit must not abort the
                # rest of the fan-out (the send itself already succeeded).
                logger.exception(
                    "Failed to emit email_sent workflow event newsletter_id=%s",
                    newsletter_id,
                )
        logger.info(
            "email_sent_workflow_events_emitted newsletter_id=%s count=%s",
            newsletter_id,
            emitted,
        )
