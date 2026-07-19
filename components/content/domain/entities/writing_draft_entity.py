"""Domain entity for a WritingDraft.

Covers free-form artifacts (letter / update / summary / memo / blog)
AND entity-scoped updates (recipient_update / project_update /
event_update / campaign_update). The latter four carry a
``related_entity_type`` + ``related_entity_id`` pair so the editor can
pre-load context and the published draft can be surfaced in the
entity's activity feed.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID

from components.content.domain.enums import WritingDraftKind, WritingDraftStatus


_ENTITY_SCOPED_KINDS = {
    WritingDraftKind.RECIPIENT_UPDATE: "recipient",
    WritingDraftKind.PROJECT_UPDATE: "project",
    WritingDraftKind.EVENT_UPDATE: "event",
    WritingDraftKind.CAMPAIGN_UPDATE: "campaign",
}


@dataclass(frozen=True)
class WritingDraftEntity:
    """
    Domain entity for an ad-hoc text artifact authored in the Writing surface.

    Drafts are workspace-scoped, author-owned, and use a Kind
    discriminator so the same model carries letters / updates /
    summaries / memos / blogs / recipient updates / project updates /
    event updates / campaign updates. Newsletters live in their own
    Newsletter entity because they carry subscriber M2M + publication
    state that's heavier than what a draft needs.

    Optional FK to a WritingTemplate captures the template a draft was
    seeded from (useful for analytics; not load-bearing).

    ``related_entity_type`` + ``related_entity_id`` link entity-scoped
    drafts (recipient_update / project_update / event_update /
    campaign_update) to the workspace entity they're about. The pair is
    REQUIRED for those four kinds and MUST be empty for the free-form
    kinds — ``__post_init__`` enforces both directions.
    """

    id: UUID
    workspace_id: UUID
    title: str
    body_html: str
    kind: str
    status: str
    author_id: int
    created_at: datetime.datetime
    updated_at: datetime.datetime
    template_id: UUID | None = None
    pdf_key: str = ""
    pdf_generated_at: datetime.datetime | None = None
    ai_drafted: bool = False
    related_entity_type: str = ""
    related_entity_id: UUID | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("WritingDraftEntity.workspace_id is required.")
        if not self.title:
            raise ValueError("WritingDraftEntity.title is required.")
        if not self.author_id:
            raise ValueError("WritingDraftEntity.author_id is required.")
        WritingDraftKind.validate(self.kind)
        WritingDraftStatus.validate(self.status)

        expected_type = _ENTITY_SCOPED_KINDS.get(self.kind)
        if expected_type is not None:
            if not self.related_entity_id:
                raise ValueError(
                    f"WritingDraftEntity kind={self.kind!r} requires "
                    "related_entity_id."
                )
            if self.related_entity_type != expected_type:
                raise ValueError(
                    f"WritingDraftEntity kind={self.kind!r} requires "
                    f"related_entity_type={expected_type!r}, got "
                    f"{self.related_entity_type!r}."
                )
        else:
            if self.related_entity_type or self.related_entity_id:
                raise ValueError(
                    f"WritingDraftEntity kind={self.kind!r} must not "
                    "carry related_entity_* fields."
                )

    @property
    def is_draft(self) -> bool:
        return self.status == WritingDraftStatus.DRAFT

    @property
    def is_published(self) -> bool:
        return self.status == WritingDraftStatus.PUBLISHED

    @property
    def is_archived(self) -> bool:
        return self.status == WritingDraftStatus.ARCHIVED

    @property
    def has_pdf(self) -> bool:
        return bool(self.pdf_key)
