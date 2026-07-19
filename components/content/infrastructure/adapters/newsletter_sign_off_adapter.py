"""Sign-off adapter for newsletters (read-side retrofit — Phase 5).

Newsletters already have a correct human gate: the cadence task drafts a row
at ``AI_DRAFTED`` and the ONLY path to ``SENT`` is a human-triggered
``SendNewsletterUseCase``. Nothing about that changes here. This adapter is a
pure read-side projection that lets the sign-off kernel *speak about* a
newsletter — surface it in the unified sign-off queue with the same review
state + reviewer receipts as every other AI artifact — without touching how a
newsletter is drafted, scheduled, or sent.

State mapping (Newsletter.status -> ReviewState):

===================  =================  ================================================
Newsletter status    ReviewState        Why
===================  =================  ================================================
``AI_DRAFTED``       ``PENDING``        AI content awaiting the human Send.
``DRAFT``            ``APPROVED``       Human-authored / human-edited (no longer AI):
                                        a human already owns this copy.
``SCHEDULED``        ``APPROVED``       Human approved + set a send-at time.
``SENDING``          ``APPROVED``       Batch dispatch in flight after human approval.
``SENT``             ``APPROVED``       Human acted; it went out.
``SEND_FAILED``      ``CHANGES_REQUESTED``  Dispatch failed; needs a human to fix + retry.
``ARCHIVED``         ``REJECTED``       Shelved / withdrawn.
===================  =================  ================================================

``set_state`` is intentionally NOT implemented: the real transitions are owned
by the Send / Schedule / Archive use cases. It raises ``NotImplementedError``
so no caller can silently believe it drove a newsletter transition through the
kernel. When the Phase-6 queue approves a newsletter it will invoke the
content context's ``SendNewsletterUseCase``, not this method.
"""

from __future__ import annotations

import logging

from components.content.domain.enums import NewsletterStatus
from components.content.infrastructure.adapters.sign_off_receipts_builder import (
    build_receipts_from_html,
    collect_grounding_values,
)
from components.sign_off.application.ports.sign_off_port import SignOffPort
from components.sign_off.application.services.sign_off_item_builder import build_sign_off_item
from components.sign_off.domain.value_objects.review_state import ReviewState
from components.sign_off.domain.value_objects.reviewer_receipts import ReviewerReceipts
from components.sign_off.domain.value_objects.sign_off_item import SignOffItem
from components.sign_off.domain.value_objects.sign_off_target import Audience, SignOffTarget
from components.shared_kernel.domain.errors import NotFoundError

logger = logging.getLogger(__name__)

_ARTIFACT_TYPE = "newsletter"

_STATE_BY_STATUS: dict[str, ReviewState] = {
    NewsletterStatus.AI_DRAFTED: ReviewState.PENDING,
    NewsletterStatus.DRAFT: ReviewState.APPROVED,
    NewsletterStatus.SCHEDULED: ReviewState.APPROVED,
    NewsletterStatus.SENDING: ReviewState.APPROVED,
    NewsletterStatus.SENT: ReviewState.APPROVED,
    NewsletterStatus.SEND_FAILED: ReviewState.CHANGES_REQUESTED,
    NewsletterStatus.ARCHIVED: ReviewState.REJECTED,
}
# Statuses that keep a newsletter in the pending-sign-off queue: an AI draft
# awaiting the human Send (PENDING), and a failed send awaiting a fix
# (CHANGES_REQUESTED).
_PENDING_STATUSES = (NewsletterStatus.AI_DRAFTED, NewsletterStatus.SEND_FAILED)


class NewsletterSignOffAdapter(SignOffPort):
    """Maps the sign-off kernel onto the ``Newsletter`` row (read-only)."""

    def artifact_type(self) -> str:
        return _ARTIFACT_TYPE

    def get_state(self, artifact_id: str) -> ReviewState:
        newsletter = self._get_newsletter(artifact_id)
        # A newsletter's status enum always maps to a known review state; if a
        # new status is ever added without a mapping, surface it loudly rather
        # than defaulting to a state that would silently gate/ungate a send.
        try:
            return _STATE_BY_STATUS[newsletter.status]
        except KeyError as exc:
            raise NotFoundError(
                f"newsletter {artifact_id} has unmapped status {newsletter.status!r}"
            ) from exc

    def set_state(self, artifact_id: str, state: ReviewState) -> None:
        raise NotImplementedError(
            "NewsletterSignOffAdapter is read-only: newsletter transitions are "
            "owned by SendNewsletterUseCase / the schedule + archive use cases. "
            "The sign-off queue must invoke those use cases, not set_state."
        )

    def build_receipts(self, artifact_id: str) -> ReviewerReceipts:
        newsletter = self._get_newsletter(artifact_id)
        grounding = collect_grounding_values(
            newsletter.content_payload or {}, newsletter.metadata or {}
        )
        return build_receipts_from_html(newsletter.content_html or "", grounding)

    def target(self, artifact_id: str) -> SignOffTarget:
        # Confirm the artifact exists so target() fails the same way as the
        # other methods for an unknown id.
        self._get_newsletter(artifact_id)
        # Newsletters go out to subscribers — always an external audience.
        return SignOffTarget(audience=Audience.EXTERNAL)

    def workspace_id(self, artifact_id: str) -> str | None:
        from infrastructure.persistence.content.models import Newsletter

        row = (
            Newsletter.objects.filter(pk=artifact_id)
            .values_list("workspace_id", flat=True)
            .first()
        )
        return str(row) if row else None

    # ── Unified queue surface (Phase 6a) ─────────────────────────────────────

    def list_pending(self, workspace_id: str) -> list[SignOffItem]:
        from infrastructure.persistence.content.models import Newsletter

        newsletters = Newsletter.objects.filter(
            workspace_id=workspace_id,
            status__in=_PENDING_STATUSES,
        ).only("id", "title", "created_at")
        return [
            build_sign_off_item(
                self,
                str(newsletter.id),
                title=newsletter.title,
                workspace_id=str(workspace_id),
                created_at=newsletter.created_at,
            )
            for newsletter in newsletters
        ]

    def approve(
        self, artifact_id: str, *, actor_id: str, override_reason: str | None = None
    ) -> None:
        # Approving an AI-drafted newsletter IS sending it — the only path to
        # SENT. Delegate to the content context's SendNewsletterUseCase; we do
        # NOT reimplement dispatch. ``override_reason`` (RED gate already cleared
        # by the queue service) doubles as the faithfulness override so a
        # reviewer who consciously approved a flagged draft isn't re-blocked by
        # the send-time faithfulness gate.
        from uuid import UUID

        from django.utils import timezone

        from components.content.application.providers.writing_provider import (
            WritingProvider,
        )

        WritingProvider().build_send_newsletter().execute(
            newsletter_id=UUID(str(artifact_id)),
            triggered_by_user_id=actor_id,
            now=timezone.now(),
            override_unverified=bool(override_reason and override_reason.strip()),
        )

    def request_changes(
        self, artifact_id: str, *, actor_id: str, codes: tuple[str, ...] = (), note: str = ""
    ) -> None:
        # A newsletter has no distinct "changes requested" status (SEND_FAILED
        # is reserved for an actual failed dispatch). Requesting changes leaves
        # the row AI_DRAFTED so it stays in the queue; the reviewer's note is
        # captured by the queue-level audit trail. We only confirm the row
        # exists so an unknown id fails like the other decision methods.
        self._get_newsletter(artifact_id)

    def reject(
        self, artifact_id: str, *, actor_id: str, codes: tuple[str, ...] = (), note: str = ""
    ) -> None:
        # Rejecting shelves the newsletter — archive it via the store port's
        # existing ARCHIVED transition (maps back to ReviewState.REJECTED).
        from uuid import UUID

        from components.content.application.providers.newsletter_store_repository_provider import (
            get_newsletter_store_repository_provider,
        )

        get_newsletter_store_repository_provider().repository().archive(
            newsletter_id=UUID(str(artifact_id))
        )

    # ── Feedback → eval capture (Phase 6c) ───────────────────────────────────

    def capture_for_eval(self, artifact_id: str) -> dict | None:
        # Same content + grounding the receipts builder verifies against, so an
        # eval example carries the exact generated copy and the facts it should
        # have been faithful to.
        newsletter = self._get_newsletter(artifact_id)
        grounding = collect_grounding_values(
            newsletter.content_payload or {}, newsletter.metadata or {}
        )
        return {
            "generated_content": newsletter.content_html or "",
            "grounding_texts": grounding,
            "prompt_id": "content.newsletter",
        }

    # ── internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _get_newsletter(artifact_id: str):
        from infrastructure.persistence.content.models import Newsletter

        newsletter = Newsletter.objects.filter(pk=artifact_id).first()
        if newsletter is None:
            raise NotFoundError(f"newsletter {artifact_id} not found")
        return newsletter
