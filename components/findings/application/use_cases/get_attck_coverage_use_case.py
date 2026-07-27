"""Read the materialized ATT&CK coverage + decide whether it needs a refresh.

Lazy materialization: the read returns whatever is materialized (a thin single-row
SELECT) and reports ``is_stale`` so the caller can enqueue an async recompute — the
heavy aggregation never runs in the request path (perf rule §6).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from components.findings.application.ports.attck_coverage_port import (
    AttckCoverageStorePort,
    CoverageSnapshot,
)

DEFAULT_TTL_SECONDS = 300


class GetAttckCoverageUseCase:
    def __init__(self, *, store: AttckCoverageStorePort) -> None:
        self._store = store

    def execute(
        self, workspace_id: UUID, now: datetime, *, ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> tuple[CoverageSnapshot, bool]:
        snapshot = self._store.get(workspace_id)
        if not snapshot.is_materialized:
            return snapshot, True
        age = (now - snapshot.computed_at).total_seconds()
        return snapshot, age > ttl_seconds
