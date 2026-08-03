"""Use case: record a proposed-fix preview onto a finding's board Task (ADR 0012 P6).

The ``project`` context owns the board ``Task``, so it owns this write. The
integrations preview flow delegates here through :class:`RecordFindingPreviewPort`
instead of reaching into ``project``'s ORM — keeping the finding-provenance write on
the owning side of the boundary (architecture-manifesto Rule 2 / architecture-skill C2).

No Django imports — depends only on ports.
"""

from __future__ import annotations

from components.project.application.ports.record_finding_preview_port import (
    RecordFindingPreviewCommand,
    RecordFindingPreviewPort,
    RecordFindingPreviewResult,
)


class RecordFindingPreviewUseCase:
    def __init__(self, port: RecordFindingPreviewPort) -> None:
        self._port = port

    def execute(self, *, command: RecordFindingPreviewCommand) -> RecordFindingPreviewResult:
        return self._port.record_preview(command=command)
