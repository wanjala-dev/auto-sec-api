"""Read the materialized ATT&CK coverage + decide whether it needs a refresh.

Lazy materialization: the read returns whatever is materialized (a thin single-row
SELECT) and reports ``is_stale`` so the caller can enqueue an async recompute — the
heavy aggregation never runs in the request path (perf rule §6).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from components.findings.application.ports.attck_coverage_port import (
    AttckCoverageStorePort,
    CoverageSnapshot,
)

DEFAULT_TTL_SECONDS = 300


def _as_aware(dt: datetime) -> datetime:
    """Coerce a datetime to tz-aware (naive → UTC) so the staleness subtraction never
    trips on a naive/aware mismatch. The project runs ``USE_TZ=False`` (the ORM returns
    naive datetimes), so the caller should pass ``django.utils.timezone.now()``; this is
    the belt-and-suspenders that keeps the use case correct for any caller."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class GetAttckCoverageUseCase:
    def __init__(self, *, store: AttckCoverageStorePort) -> None:
        self._store = store

    def execute(
        self, workspace_id: UUID, now: datetime, *, ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> tuple[CoverageSnapshot, bool]:
        snapshot = self._store.get(workspace_id)
        if not snapshot.is_materialized:
            return snapshot, True
        age = (_as_aware(now) - _as_aware(snapshot.computed_at)).total_seconds()
        return snapshot, age > ttl_seconds
