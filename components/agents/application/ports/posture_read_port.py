"""Port: read the agents context's OWN ``ai.*`` telemetry the posture surfaces need.

The security-posture services (``posture_service`` / ``posture_dashboard_service``)
compute every number from rows that already exist. The board-finding facts come
from the ``project`` context through its ``PostureFactsPort`` (burndown PR-5); the
SAME-context ``ai.*`` telemetry — deep-run cost records, human up/down votes, and
the ``AiActionDailyRollup`` read model — used to be read inline off
``infrastructure.persistence.ai`` from the application layer (Rule-2 violation).
This port is that same-context read seam; the ORM lives in the adapter, the pure
``compute_*`` functions still do all the classification off the returned rows.

Every method is workspace-scoped (tenant isolation) and read-only. Returned
values are plain dicts/lists the ``compute_*`` functions already consume — no ORM
instance crosses the seam.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class PostureReadPort(ABC):
    """Read the agents-owned ``ai.*`` telemetry the posture aggregates need."""

    @abstractmethod
    def collect_deep_run_cost_rows(self, *, workspace_id: str, window_start: datetime) -> list[dict[str, Any]]:
        """DeepRuns created ``>= window_start`` for a workspace, as the rows
        ``compute_fleet_health`` consumes: ``{"id": str, "status": str,
        "cost_records": list}`` where ``cost_records`` is
        ``state['run_metadata']['cost_usd_records']`` (a list, or ``[]``).
        """

    @abstractmethod
    def collect_feedback_ratings(self, *, workspace_id: str, window_start: datetime) -> list[dict[str, Any]]:
        """Human up/down votes on assistant messages in the window for a
        workspace, as ``[{"rating": str}, ...]``. Workspace scoping walks the
        conversation ``metadata.workspace_id`` (no FK), matching the AI quality
        rollup task's traversal.
        """

    @abstractmethod
    def collect_action_rollup_series(
        self, *, workspace_id: str, since_date: date
    ) -> tuple[dict[str, int], dict[str, float], bool]:
        """Runs/day + cost/day from the ``AiActionDailyRollup`` read model for a
        workspace, for rollup rows with ``date >= since_date``.

        Returns ``(runs_by_date, cost_by_date, present)`` where the two maps are
        keyed by ISO date and ``present`` is True iff any rollup row matched —
        distinguishing "no rows" from an all-zero calendar so the dashboard's
        ``no_data`` honesty holds.
        """
