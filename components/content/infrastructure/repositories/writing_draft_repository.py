"""ORM-backed WritingDraft store + reads (combined — simpler entity)."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from components.content.application.ports.writing_draft_reader_port import (
    WritingDraftReaderPort,
)
from components.content.application.ports.writing_draft_store_port import (
    WritingDraftStorePort,
)
from components.content.domain.entities.writing_draft_entity import (
    WritingDraftEntity,
)
from components.content.domain.enums import WritingDraftKind, WritingDraftStatus
from components.content.domain.errors import (
    ContentValidationError,
    WritingDraftNotFoundError,
)


def _to_entity(row) -> WritingDraftEntity:
    return WritingDraftEntity(
        id=row.id,
        workspace_id=row.workspace_id,
        # READS must never die on stored data: a legacy row that slipped
        # through with an empty title (the 2026-07-12 write-then-validate
        # bug) 500'd every GET. The write path now rejects blank titles;
        # this fallback only tolerates historic rows.
        title=row.title or "Untitled",
        body_html=row.body_html,
        kind=row.kind,
        status=row.status,
        author_id=row.author_id,
        template_id=row.template_id,
        pdf_key=row.pdf_key or "",
        pdf_generated_at=row.pdf_generated_at,
        ai_drafted=row.ai_drafted,
        related_entity_type=getattr(row, "related_entity_type", "") or "",
        related_entity_id=getattr(row, "related_entity_id", None),
        metadata=dict(row.metadata or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class WritingDraftRepository(WritingDraftStorePort, WritingDraftReaderPort):
    # ── Store ─────────────────────────────────────────────────────────

    def create(
        self,
        *,
        workspace_id: UUID,
        author_id: int,
        title: str,
        body_html: str,
        kind: str,
        template_id: UUID | None = None,
        ai_drafted: bool = False,
        related_entity_type: str = "",
        related_entity_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingDraftEntity:
        from infrastructure.persistence.content.models import WritingDraft

        WritingDraftKind.validate(kind)
        row = WritingDraft.objects.create(
            workspace_id=workspace_id,
            author_id=author_id,
            title=title,
            body_html=body_html,
            kind=kind,
            template_id=template_id,
            ai_drafted=ai_drafted,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            metadata=metadata or {},
        )
        return _to_entity(row)

    def update_body(
        self,
        *,
        draft_id: UUID,
        title: str | None = None,
        body_html: str | None = None,
        metadata: dict | None = None,
    ) -> WritingDraftEntity:
        """Partial update: only fields the caller PROVIDED are written.

        Validate-then-write, never write-then-validate: the old shape
        defaulted a missing title to "" and persisted it before entity
        construction raised — corrupting the row so every subsequent
        READ 500'd on the stored empty title (bit a real save on
        2026-07-12).
        """
        from infrastructure.persistence.content.models import WritingDraft

        if title is not None and not title.strip():
            raise ContentValidationError("Draft title cannot be blank.")

        try:
            row = WritingDraft.objects.get(pk=draft_id)
        except WritingDraft.DoesNotExist as exc:
            raise WritingDraftNotFoundError(str(draft_id)) from exc

        update_fields = ["updated_at"]
        if title is not None:
            row.title = title.strip()
            update_fields.append("title")
        if body_html is not None:
            row.body_html = body_html
            update_fields.append("body_html")
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise ContentValidationError("Draft metadata must be an object.")
            # Full replace of the metadata document when provided — the
            # partial-update contract is at the FIELD level (absent field
            # untouched), same as title/body_html. EXCEPT server-written
            # keys: ``ai_provenance`` is recorded by the ask-ai endpoint,
            # so a client saving from a snapshot taken before that run
            # must not silently erase it (task #22).
            preserved = (row.metadata or {}).get("ai_provenance")
            if preserved is not None and "ai_provenance" not in metadata:
                metadata = {**metadata, "ai_provenance": preserved}
            row.metadata = metadata
            update_fields.append("metadata")
        row.save(update_fields=update_fields)
        return _to_entity(row)

    def merge_metadata_key(self, *, draft_id: UUID, key: str, value: dict) -> None:
        from infrastructure.persistence.content.models import WritingDraft

        try:
            row = WritingDraft.objects.get(pk=draft_id)
        except WritingDraft.DoesNotExist as exc:
            raise WritingDraftNotFoundError(str(draft_id)) from exc
        metadata = dict(row.metadata or {})
        metadata[key] = value
        row.metadata = metadata
        row.save(update_fields=["metadata", "updated_at"])

    def publish(self, *, draft_id: UUID) -> WritingDraftEntity:
        from infrastructure.persistence.content.models import WritingDraft

        try:
            row = WritingDraft.objects.get(pk=draft_id)
        except WritingDraft.DoesNotExist as exc:
            raise WritingDraftNotFoundError(str(draft_id)) from exc
        row.status = WritingDraftStatus.PUBLISHED
        row.save(update_fields=["status", "updated_at"])
        return _to_entity(row)

    def archive(self, *, draft_id: UUID) -> WritingDraftEntity:
        from infrastructure.persistence.content.models import WritingDraft

        try:
            row = WritingDraft.objects.get(pk=draft_id)
        except WritingDraft.DoesNotExist as exc:
            raise WritingDraftNotFoundError(str(draft_id)) from exc
        row.status = WritingDraftStatus.ARCHIVED
        row.save(update_fields=["status", "updated_at"])
        return _to_entity(row)

    def attach_pdf(
        self,
        *,
        draft_id: UUID,
        pdf_key: str,
        pdf_generated_at: datetime.datetime,
    ) -> WritingDraftEntity:
        from infrastructure.persistence.content.models import WritingDraft

        try:
            row = WritingDraft.objects.get(pk=draft_id)
        except WritingDraft.DoesNotExist as exc:
            raise WritingDraftNotFoundError(str(draft_id)) from exc
        row.pdf_key = pdf_key
        row.pdf_generated_at = pdf_generated_at
        row.save(update_fields=["pdf_key", "pdf_generated_at", "updated_at"])
        return _to_entity(row)

    def delete(self, *, draft_id: UUID) -> None:
        from infrastructure.persistence.content.models import WritingDraft

        WritingDraft.objects.filter(pk=draft_id).delete()

    # ── Read ──────────────────────────────────────────────────────────

    def get(self, *, draft_id: UUID) -> WritingDraftEntity | None:
        from infrastructure.persistence.content.models import WritingDraft

        row = WritingDraft.objects.filter(pk=draft_id).first()
        return _to_entity(row) if row else None

    def list_for_workspace(
        self,
        *,
        workspace_id: UUID,
        kind: str | None = None,
        status: str | None = None,
        author_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[WritingDraftEntity]:
        from infrastructure.persistence.content.models import WritingDraft

        qs = WritingDraft.objects.filter(workspace_id=workspace_id)
        if kind:
            qs = qs.filter(kind=kind)
        if status:
            qs = qs.filter(status=status)
        if author_id is not None:
            qs = qs.filter(author_id=author_id)
        return [_to_entity(row) for row in qs[offset : offset + limit]]
