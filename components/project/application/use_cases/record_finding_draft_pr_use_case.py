"""Use case: record a draft-PR outcome onto a finding's board Task.

The ``project`` context owns the board ``Task``, so it owns this write. Another
context (integrations' VCS draft-PR capability) delegates here through
:class:`RecordFindingDraftPrPort` instead of reaching into ``project``'s ORM —
keeping the finding-provenance write on the owning side of the boundary
(architecture-manifesto Rule 2 / architecture-skill C2).

No Django imports — depends only on ports.
"""

from __future__ import annotations

from components.project.application.ports.record_finding_draft_pr_port import (
    RecordFindingDraftPrCommand,
    RecordFindingDraftPrPort,
    RecordFindingDraftPrResult,
)


class RecordFindingDraftPrUseCase:
    def __init__(self, port: RecordFindingDraftPrPort) -> None:
        self._port = port

    def execute(self, *, command: RecordFindingDraftPrCommand) -> RecordFindingDraftPrResult:
        return self._port.record_draft_pr(command=command)
