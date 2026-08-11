"""Use case: record that a finding's draft PR was closed without merging.

The rejection counterpart to :class:`RecordFindingDraftPrUseCase`. The ``project``
context owns the board ``Task``, so it owns this write too — the caller that can
read a code host asks for it through :class:`RecordFindingDraftPrPort` rather than
reaching into ``project``'s ORM (architecture-manifesto Rule 2 / skill C2).

No Django imports — depends only on ports.
"""

from __future__ import annotations

from components.project.application.ports.record_finding_draft_pr_port import (
    MarkDraftPrRejectedCommand,
    MarkDraftPrRejectedResult,
    RecordFindingDraftPrPort,
)


class MarkFindingDraftPrRejectedUseCase:
    def __init__(self, port: RecordFindingDraftPrPort) -> None:
        self._port = port

    def execute(self, *, command: MarkDraftPrRejectedCommand) -> MarkDraftPrRejectedResult:
        return self._port.mark_draft_pr_rejected(command=command)
