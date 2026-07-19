"""Port for WritingTemplate persistence writes."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from components.content.domain.entities.writing_template_entity import (
    WritingTemplateEntity,
)


class WritingTemplateStorePort(Protocol):
    def create(
        self,
        *,
        name: str,
        description: str,
        kind: str,
        body_html: str,
        is_seeded: bool = False,
        workspace_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WritingTemplateEntity: ...

    def update(
        self,
        *,
        template_id: UUID,
        name: str,
        description: str,
        body_html: str,
    ) -> WritingTemplateEntity: ...

    def delete(self, *, template_id: UUID) -> None: ...
