"""Mutation DTO: update (rename/recolor/describe/restore/soft-delete) a tag (ADR 0015 D5/D6).

``None`` = leave unchanged. ``name`` re-derives the slug (rename); ``is_deleted``
False = restore, True = soft delete.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class UpdateTagCommand:
    workspace_id: UUID
    tag_id: UUID
    name: str | None = None
    color: str | None = None
    description: str | None = None
    is_deleted: bool | None = None
    actor_id: str | None = None
