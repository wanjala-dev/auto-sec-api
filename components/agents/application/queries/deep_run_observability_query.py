"""Application-layer query objects for deep-run observability.

Thin wrappers over ``DeepRunQueryPort`` — the controller calls these
rather than touching the port directly so tests can inject a fake port
without mocking the controller.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from components.agents.application.ports.deep_run_query_port import (
    DeepRunEventView,
    DeepRunQueryPort,
    DeepRunSnapshotView,
    DeepRunStatsView,
)


@dataclass
class FetchDeepRunSnapshotQuery:
    """Return the snapshot for a given ``plan_id`` (or ``None``)."""

    port: DeepRunQueryPort

    def execute(self, plan_id: str) -> DeepRunSnapshotView | None:
        return self.port.get_snapshot(plan_id)


@dataclass
class FetchDeepRunEventsQuery:
    """Return the event page for a given ``plan_id``."""

    port: DeepRunQueryPort

    def execute(
        self,
        plan_id: str,
        *,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[DeepRunEventView]:
        return self.port.list_events(plan_id, since=since, limit=limit)


@dataclass
class FetchDeepRunStatsQuery:
    """Return workspace-level (or global) aggregate stats."""

    port: DeepRunQueryPort

    def execute(
        self,
        workspace_id: str | None = None,
        *,
        since: datetime | None = None,
    ) -> DeepRunStatsView:
        return self.port.get_workspace_stats(workspace_id, since=since)
