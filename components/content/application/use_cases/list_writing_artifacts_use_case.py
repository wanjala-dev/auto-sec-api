"""Use case: cross-context unified list of writing artifacts.

Consumed by ``shared_platform``'s unified-documents controller. This
delegates straight through to ``WritingArtifactsPort`` — the use case
exists so cross-context callers go through ``application`` rather than
touching infrastructure directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from components.content.application.ports.writing_artifacts_port import (
    WritingArtifactSummary,
    WritingArtifactsPort,
)


@dataclass
class ListWritingArtifactsUseCase:
    writing_artifacts: WritingArtifactsPort

    def execute(
        self,
        *,
        workspace_id: UUID,
        kinds: Sequence[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[WritingArtifactSummary]:
        return self.writing_artifacts.list_for_workspace(
            workspace_id=workspace_id,
            kinds=kinds,
            limit=limit,
            offset=offset,
        )
