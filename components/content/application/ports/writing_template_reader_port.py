"""Port for WritingTemplate reads."""

from __future__ import annotations

from typing import Protocol, Sequence
from uuid import UUID

from components.content.domain.entities.writing_template_entity import (
    WritingTemplateEntity,
)


class WritingTemplateReaderPort(Protocol):
    def get(self, *, template_id: UUID) -> WritingTemplateEntity | None: ...

    def list_available(
        self,
        *,
        workspace_id: UUID,
        kind: str | None = None,
    ) -> Sequence[WritingTemplateEntity]:
        """Return all templates visible to ``workspace_id``: globally seeded
        templates (workspace=NULL) plus that workspace's own templates,
        optionally filtered to a single kind."""
        ...

    def list_seeded(self, *, kind: str | None = None) -> Sequence[WritingTemplateEntity]: ...
