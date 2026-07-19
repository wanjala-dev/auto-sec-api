"""Domain entity for a WritingTemplate (seedable starter content)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID

from components.content.domain.enums import WritingTemplateKind


@dataclass(frozen=True)
class WritingTemplateEntity:
    """
    Domain entity for a writing template — a seedable starter document
    for any composable artifact (letter, update, summary, memo, newsletter,
    blog).

    Templates with workspace_id=None are global seeded templates (loaded
    via Django fixtures, available to every workspace). Templates with
    workspace_id set are workspace-owned customizations.

    Kind spans every writing artifact type, so a single template store
    serves both drafts and newsletters/blogs.
    """

    id: UUID
    name: str
    description: str
    kind: str
    body_html: str
    is_seeded: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    workspace_id: UUID | None = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("WritingTemplateEntity.name is required.")
        WritingTemplateKind.validate(self.kind)
        if self.is_seeded and self.workspace_id is not None:
            raise ValueError(
                "WritingTemplateEntity marked is_seeded must have workspace_id=None "
                "(seeded templates are global)."
            )

    @property
    def is_global(self) -> bool:
        return self.workspace_id is None

    @property
    def is_workspace_owned(self) -> bool:
        return self.workspace_id is not None
