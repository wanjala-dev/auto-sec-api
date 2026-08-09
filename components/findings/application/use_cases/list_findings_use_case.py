"""List findings from the SSOT (read side) — framework-free orchestration."""

from __future__ import annotations

from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.application.ports.finding_triage_state_port import FindingTriageStatePort
from components.findings.application.queries.list_findings_query import (
    FindingPage,
    ListFindingsQuery,
)
from components.findings.application.services.triage_state_attachment import attach_triage_states


class ListFindingsUseCase:
    """Return a filtered, paginated page of findings for a workspace.

    Reads through the store port (never the ORM). The store applies the filter +
    window and returns entities; this use case pairs them with the total for the
    same filter so the caller can render pagination.
    """

    def __init__(self, store: FindingStorePort, triage_states: FindingTriageStatePort | None = None):
        self._store = store
        self._triage_states = triage_states

    def execute(self, query: ListFindingsQuery) -> FindingPage:
        items = self._store.list_ranked_findings(
            query.workspace_id,
            severity=query.severity,
            status=query.status,
            source=query.source,
            asset_urn=query.asset_urn,
            tag_groups=query.tag_groups,
            exclude_tag_ids=query.exclude_tag_ids,
            order_by=query.order_by,
            limit=query.limit,
            offset=query.offset,
        )
        total = self._store.count_findings(
            query.workspace_id,
            severity=query.severity,
            status=query.status,
            source=query.source,
            asset_urn=query.asset_urn,
            tag_groups=query.tag_groups,
            exclude_tag_ids=query.exclude_tag_ids,
        )
        items = attach_triage_states(items, self._triage_states, workspace_id=query.workspace_id)
        return FindingPage(items=items, total=total, limit=query.limit, offset=query.offset)
