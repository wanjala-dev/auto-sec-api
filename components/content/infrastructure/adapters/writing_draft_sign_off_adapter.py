"""Sign-off adapter for writing drafts / blogs (read-side retrofit — Phase 5).

Writing drafts already have a correct human gate: an AI-drafted row lands at
``status=DRAFT`` with ``ai_drafted=True`` and the ONLY path to ``PUBLISHED`` is
a human-triggered ``PublishWritingDraftUseCase``. Nothing about that changes
here. This adapter is a pure read-side projection so the sign-off kernel can
surface a draft in the unified queue with the same review state + reviewer
receipts as every other AI artifact.

Only AI-drafted drafts are gated. A human-authored draft (``ai_drafted=False``)
was written by a person start to finish, so it is treated as already
``APPROVED`` — it never needs a sign-off.

State mapping:

================================  =================  ==========================================
Draft                             ReviewState        Why
================================  =================  ==========================================
``ai_drafted=False`` (any status) ``APPROVED``       Human-authored — not gated.
``ai_drafted=True`` + ``DRAFT``   ``PENDING``        AI content awaiting the human Publish.
``PUBLISHED``                     ``APPROVED``       Human published it.
``ARCHIVED``                      ``REJECTED``       Shelved / withdrawn.
================================  =================  ==========================================

``set_state`` is intentionally NOT implemented: the real transition is owned by
``PublishWritingDraftUseCase``. It raises ``NotImplementedError`` so no caller
can silently believe it drove a draft transition through the kernel.

Target audience: a ``blog`` is a public transparency surface -> ``EXTERNAL``;
every other kind (letter / update / summary / memo + the entity-scoped update
kinds) is workspace-internal -> ``INTERNAL_TEAM``.
"""

from __future__ import annotations

import logging

from components.content.domain.enums import WritingDraftKind, WritingDraftStatus
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

_ARTIFACT_TYPE = "writing_draft"


class WritingDraftSignOffAdapter(SignOffPort):
    """Maps the sign-off kernel onto the ``WritingDraft`` row (read-only)."""

    def artifact_type(self) -> str:
        return _ARTIFACT_TYPE

    def get_state(self, artifact_id: str) -> ReviewState:
        draft = self._get_draft(artifact_id)
        # Human-authored drafts are never gated — a person owns the copy.
        if not draft.ai_drafted:
            return ReviewState.APPROVED
        if draft.status == WritingDraftStatus.PUBLISHED:
            return ReviewState.APPROVED
        if draft.status == WritingDraftStatus.ARCHIVED:
            return ReviewState.REJECTED
        # ai_drafted and still an editable DRAFT -> awaiting the human Publish.
        return ReviewState.PENDING

    def set_state(self, artifact_id: str, state: ReviewState) -> None:
        raise NotImplementedError(
            "WritingDraftSignOffAdapter is read-only: the DRAFT -> PUBLISHED "
            "transition is owned by PublishWritingDraftUseCase. The sign-off "
            "queue must invoke that use case, not set_state."
        )

    def build_receipts(self, artifact_id: str) -> ReviewerReceipts:
        draft = self._get_draft(artifact_id)
        grounding = collect_grounding_values(draft.metadata or {})
        return build_receipts_from_html(draft.body_html or "", grounding)

    def target(self, artifact_id: str) -> SignOffTarget:
        draft = self._get_draft(artifact_id)
        if draft.kind == WritingDraftKind.BLOG:
            # Blogs are a public transparency surface.
            return SignOffTarget(audience=Audience.EXTERNAL)
        # Letters, updates, summaries, memos + entity-scoped updates stay
        # inside the workspace.
        return SignOffTarget(audience=Audience.INTERNAL_TEAM)

    def workspace_id(self, artifact_id: str) -> str | None:
        from infrastructure.persistence.content.models import WritingDraft

        row = (
            WritingDraft.objects.filter(pk=artifact_id)
            .values_list("workspace_id", flat=True)
            .first()
        )
        return str(row) if row else None

    # ── Unified queue surface (Phase 6a) ─────────────────────────────────────

    def list_pending(self, workspace_id: str) -> list[SignOffItem]:
        from infrastructure.persistence.content.models import WritingDraft

        # Only AI-drafted drafts still in DRAFT are gated (a human-authored
        # draft is APPROVED, a published one APPROVED, an archived one REJECTED).
        drafts = WritingDraft.objects.filter(
            workspace_id=workspace_id,
            ai_drafted=True,
            status=WritingDraftStatus.DRAFT,
        ).only("id", "title", "created_at")
        return [
            build_sign_off_item(
                self,
                str(draft.id),
                title=draft.title,
                workspace_id=str(workspace_id),
                created_at=draft.created_at,
            )
            for draft in drafts
        ]

    def approve(
        self, artifact_id: str, *, actor_id: str, override_reason: str | None = None
    ) -> None:
        # Approving an AI-drafted draft IS publishing it. Delegate to the
        # content context's PublishWritingDraftUseCase; we do NOT reimplement
        # the publish transition or its domain event.
        from uuid import UUID

        from django.utils import timezone

        from components.content.application.providers.writing_provider import (
            WritingProvider,
        )

        WritingProvider().build_publish_writing_draft().execute(
            draft_id=UUID(str(artifact_id)),
            actor_id=actor_id,
            now=timezone.now(),
        )

    def request_changes(
        self, artifact_id: str, *, actor_id: str, codes: tuple[str, ...] = (), note: str = ""
    ) -> None:
        # A DRAFT has no distinct "changes requested" status — leaving it DRAFT
        # keeps it editable and in the queue. The reviewer's note is captured by
        # the queue-level audit trail. Confirm the row exists so an unknown id
        # fails like the other decision methods.
        self._get_draft(artifact_id)

    def reject(
        self, artifact_id: str, *, actor_id: str, codes: tuple[str, ...] = (), note: str = ""
    ) -> None:
        # Rejecting shelves the draft — archive it via the store port's existing
        # ARCHIVED transition (maps back to ReviewState.REJECTED).
        from uuid import UUID

        from components.content.application.providers.writing_draft_repository_provider import (
            get_writing_draft_repository_provider,
        )

        get_writing_draft_repository_provider().repository().archive(
            draft_id=UUID(str(artifact_id))
        )

    # ── Feedback → eval capture (Phase 6c) ───────────────────────────────────

    def capture_for_eval(self, artifact_id: str) -> dict | None:
        # Same body + grounding the receipts builder verifies against, so an
        # eval example carries the exact generated copy and the facts it should
        # have been faithful to.
        draft = self._get_draft(artifact_id)
        grounding = collect_grounding_values(draft.metadata or {})
        return {
            "generated_content": draft.body_html or "",
            "grounding_texts": grounding,
            "prompt_id": "content.writing",
        }

    # ── internals ──────────────────────────────────────────────────────────

    @staticmethod
    def _get_draft(artifact_id: str):
        from infrastructure.persistence.content.models import WritingDraft

        draft = WritingDraft.objects.filter(pk=artifact_id).first()
        if draft is None:
            raise NotFoundError(f"writing draft {artifact_id} not found")
        return draft
