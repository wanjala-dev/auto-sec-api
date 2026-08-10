"""Use case: attach a draft PR's patch to a finding's existing board record.

The repair counterpart to :class:`RecordFindingDraftPrUseCase`. The ``project``
context owns the board ``Task``, so it owns this write too — the integrations
context (which can read a code host) asks for it through
:class:`RecordFindingDraftPrPort` rather than reaching into ``project``'s ORM
(architecture-manifesto Rule 2 / architecture-skill C2).

No Django imports — depends only on ports.
"""

from __future__ import annotations

from components.project.application.ports.record_finding_draft_pr_port import (
    AttachDraftPrPatchCommand,
    AttachDraftPrPatchResult,
    RecordFindingDraftPrPort,
)


class AttachFindingDraftPrPatchUseCase:
    def __init__(self, port: RecordFindingDraftPrPort) -> None:
        self._port = port

    def execute(self, *, command: AttachDraftPrPatchCommand) -> AttachDraftPrPatchResult:
        return self._port.attach_draft_pr_patch(command=command)
