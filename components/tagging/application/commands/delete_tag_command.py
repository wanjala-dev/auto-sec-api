"""Mutation DTO: soft-delete a tag from a workspace's vocabulary (ADR 0015 D5/D6)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class DeleteTagCommand:
    workspace_id: UUID
    tag_id: UUID
    actor_id: str | None = None
