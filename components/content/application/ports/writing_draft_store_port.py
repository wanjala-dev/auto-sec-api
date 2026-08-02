"""Port for WritingDraft persistence writes."""

from __future__ import annotations

import datetime
from typing import Any, Protocol
from uuid import UUID

from components.content.domain.entities.writing_draft_entity import (
    WritingDraftEntity,
)


class WritingDraftStorePort(Protocol):
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
    ) -> WritingDraftEntity: ...

    def update_body(
        self,
        *,
        draft_id: UUID,
        title: str | None = None,
        body_html: str | None = None,
        metadata: dict | None = None,
    ) -> WritingDraftEntity: ...

    def merge_metadata_key(self, *, draft_id: UUID, key: str, value: dict) -> None:
        """Atomically set ONE metadata key without touching the rest of
        the document — server-written keys (``ai_provenance``) use this
        so they can't race a concurrent full-metadata save."""
        ...

    def stamp_rag_indexed(
        self,
        *,
        draft_id: UUID,
        document_key: str,
        indexed_at: datetime.datetime,
    ) -> None:
        """Record that this draft was indexed into the knowledge vector
        store — stamps ``rag_indexed_at`` + ``rag_document_key`` on the
        metadata JSON without touching the rest of the document.

        Used by the ``on_writing_draft_published_index_rag`` handler; the
        RAG backfill command reads the stamp to skip already-indexed rows.
        No-op if the row is gone."""
        ...

    def publish(self, *, draft_id: UUID) -> WritingDraftEntity: ...

    def archive(self, *, draft_id: UUID) -> WritingDraftEntity: ...

    def attach_pdf(
        self,
        *,
        draft_id: UUID,
        pdf_key: str,
        pdf_generated_at: datetime.datetime,
    ) -> WritingDraftEntity: ...

    def delete(self, *, draft_id: UUID) -> None: ...
