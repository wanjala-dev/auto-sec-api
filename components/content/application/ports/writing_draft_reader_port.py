"""Port for WritingDraft reads."""

from __future__ import annotations

from typing import Protocol, Sequence
from uuid import UUID

from components.content.domain.entities.writing_draft_entity import (
    WritingDraftEntity,
)


class WritingDraftReaderPort(Protocol):
    def get(self, *, draft_id: UUID) -> WritingDraftEntity | None: ...

    def list_for_workspace(
        self,
        *,
        workspace_id: UUID,
        kind: str | None = None,
        status: str | None = None,
        author_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[WritingDraftEntity]: ...
