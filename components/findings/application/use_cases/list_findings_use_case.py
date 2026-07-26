"""List findings from the SSOT (read side) — framework-free orchestration."""

from __future__ import annotations

from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.application.queries.list_findings_query import (
    FindingPage,
    ListFindingsQuery,
)


class ListFindingsUseCase:
    """Return a filtered, paginated page of findings for a workspace.

    Reads through the store port (never the ORM). The store applies the filter +
    window and returns entities; this use case pairs them with the total for the
    same filter so the caller can render pagination.
    """

    def __init__(self, store: FindingStorePort):
        self._store = store

    def execute(self, query: ListFindingsQuery) -> FindingPage:
        items = self._store.list_findings(
            query.workspace_id,
            severity=query.severity,
            status=query.status,
            source=query.source,
            asset_urn=query.asset_urn,
            limit=query.limit,
            offset=query.offset,
        )
        total = self._store.count_findings(
            query.workspace_id,
            severity=query.severity,
            status=query.status,
            source=query.source,
            asset_urn=query.asset_urn,
        )
        return FindingPage(items=items, total=total, limit=query.limit, offset=query.offset)
