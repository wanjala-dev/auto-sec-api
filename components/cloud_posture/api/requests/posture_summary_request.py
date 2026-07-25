"""Input DTO — the cloud-posture summary query (workspace-scoped)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class PostureSummaryRequest:
    workspace_id: UUID

    @classmethod
    def from_path(cls, workspace_id: UUID) -> "PostureSummaryRequest":
        return cls(workspace_id=workspace_id)
