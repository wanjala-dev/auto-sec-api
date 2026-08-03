"""ORM adapter implementing :class:`PostureReadPort`.

Reads the agents-owned ``ai.*`` telemetry the posture surfaces need — deep-run
cost records, human votes, and the ``AiActionDailyRollup`` series — the exact
queries ``posture_service``/``posture_dashboard_service`` did inline, moved behind
the port so the application layer no longer imports persistence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from components.agents.application.ports.posture_read_port import PostureReadPort


class OrmPostureReadRepository(PostureReadPort):
    def collect_deep_run_cost_rows(self, *, workspace_id: str, window_start: datetime) -> list[dict[str, Any]]:
        from infrastructure.persistence.ai.agents.models import DeepRun

        run_rows: list[dict[str, Any]] = []
        runs = DeepRun.objects.filter(workspace_id=workspace_id, created_at__gte=window_start).only(
            "id", "status", "state"
        )
        for run in runs.iterator(chunk_size=500):
            state = run.state if isinstance(run.state, dict) else {}
            run_metadata = state.get("run_metadata") if isinstance(state.get("run_metadata"), dict) else {}
            cost_records = run_metadata.get("cost_usd_records")
            run_rows.append(
                {
                    "id": str(run.id),
                    "status": run.status,
                    "cost_records": cost_records if isinstance(cost_records, list) else [],
                }
            )
        return run_rows

    def collect_feedback_ratings(self, *, workspace_id: str, window_start: datetime) -> list[dict[str, Any]]:
        from infrastructure.persistence.ai.conversations.models import AgentResponseFeedback

        # Conversation carries workspace only in metadata JSON (no FK) — same
        # traversal the AI quality rollup task uses.
        return [
            {"rating": rating}
            for rating in AgentResponseFeedback.objects.filter(
                created_at__gte=window_start,
                message__conversation__metadata__workspace_id=str(workspace_id),
            ).values_list("rating", flat=True)
        ]

    def collect_action_rollup_series(
        self, *, workspace_id: str, since_date
    ) -> tuple[dict[str, int], dict[str, float], bool]:
        from infrastructure.persistence.ai.agents.models import AiActionDailyRollup

        runs_by_date: dict[str, int] = {}
        cost_by_date: dict[str, float] = {}
        present = False
        rows = AiActionDailyRollup.objects.filter(workspace_id=workspace_id, date__gte=since_date).only(
            "date", "runs_total", "cost_usd"
        )
        for row in rows.iterator(chunk_size=500):
            present = True
            iso = row.date.isoformat()
            runs_by_date[iso] = int(row.runs_total)
            cost_by_date[iso] = float(row.cost_usd)
        return runs_by_date, cost_by_date, present
