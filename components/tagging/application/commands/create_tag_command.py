"""Mutation DTO: create one tag in a workspace's vocabulary (ADR 0015 D6)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CreateTagCommand:
    workspace_id: UUID
    name: str
    namespace: str = ""
    color: str = ""
    description: str = ""
    kind: str = "user"
    actor_id: str | None = None
