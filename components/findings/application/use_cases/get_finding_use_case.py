"""Fetch one finding (with its contextual-risk view) from the SSOT — read side."""

from __future__ import annotations

from uuid import UUID

from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.application.ports.finding_triage_state_port import FindingTriageStatePort
from components.findings.application.queries.list_findings_query import RankedFinding
from components.findings.application.services.triage_state_attachment import attach_triage_states


class GetFindingUseCase:
    """Return one workspace-scoped finding paired with its risk view, or None.

    The read behind the HUD deep link (``?panel=findings&finding=<id>``): an
    outbound alert (e.g. Slack) must open the HUD on its exact finding regardless
    of which list page that finding sorts onto. Same row shape as the list read
    (``RankedFinding``) so the detail render matches the list rows.
    """

    def __init__(self, store: FindingStorePort, triage_states: FindingTriageStatePort | None = None):
        self._store = store
        self._triage_states = triage_states

    def execute(self, workspace_id: UUID, finding_id: UUID) -> RankedFinding | None:
        row = self._store.get_ranked_finding(workspace_id, finding_id)
        if row is None:
            return None
        return attach_triage_states([row], self._triage_states, workspace_id=workspace_id)[0]
