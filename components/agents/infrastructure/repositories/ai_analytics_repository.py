"""ORM adapter that reads the AI quality rollup tables for the analytics API.

Reads are strictly over the pre-computed ``AIModelDailyMetric`` /
``AIWorkspaceDailyMetric`` rollups + the append-only
``AIModelChangeEvent`` rows — three indexed range queries per request,
constant with respect to traffic volume (only the window length and
model count move the row counts).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from components.agents.application.ports.ai_analytics_port import (
    AIAnalyticsQueryPort,
    AIQualityOverviewView,
    DayMetricView,
    ModelChangeEventView,
    ModelDayMetricView,
)


class OrmAIAnalyticsRepository(AIAnalyticsQueryPort):
    """Django ORM implementation of :class:`AIAnalyticsQueryPort`."""

    def get_overview(self, workspace_id: str, *, days: int) -> AIQualityOverviewView:
        from infrastructure.persistence.ai.aggregations.models import (
            AIModelChangeEvent,
            AIModelDailyMetric,
            AIWorkspaceDailyMetric,
        )

        today = timezone.now().date()
        window_start = today - timedelta(days=days - 1)

        model_rows = AIModelDailyMetric.objects.filter(workspace_id=workspace_id, date__gte=window_start).order_by(
            "date", "model_used"
        )

        models_by_day: dict = defaultdict(list)
        for row in model_rows:
            models_by_day[row.date].append(
                ModelDayMetricView(
                    model=row.model_used,
                    llm_calls=row.llm_calls,
                    prompt_tokens=row.prompt_tokens,
                    completion_tokens=row.completion_tokens,
                    cost_usd=row.cost_usd,
                    latency_p50_ms=row.latency_p50_ms,
                    latency_p95_ms=row.latency_p95_ms,
                )
            )

        workspace_rows = {
            row.date: row
            for row in AIWorkspaceDailyMetric.objects.filter(workspace_id=workspace_id, date__gte=window_start)
        }

        series = []
        for offset in range(days):
            day = window_start + timedelta(days=offset)
            ws_row = workspace_rows.get(day)
            day_models = models_by_day.get(day, [])
            if ws_row is None and not day_models:
                # Zero-activity days are still emitted so the frontend
                # renders a continuous axis without gap-filling logic.
                series.append(DayMetricView(date=day))
                continue
            series.append(
                DayMetricView(
                    date=day,
                    models=tuple(day_models),
                    runs_total=ws_row.runs_total if ws_row else 0,
                    runs_completed=ws_row.runs_completed if ws_row else 0,
                    runs_failed=ws_row.runs_failed if ws_row else 0,
                    assistant_messages=ws_row.assistant_messages if ws_row else 0,
                    feedback_up=ws_row.feedback_up if ws_row else 0,
                    feedback_down=ws_row.feedback_down if ws_row else 0,
                )
            )

        change_events = tuple(
            ModelChangeEventView(
                changed_at=event.created_at,
                field=event.field,
                old_value=event.old_value,
                new_value=event.new_value,
                changed_by_id=str(event.changed_by_id) if event.changed_by_id else None,
            )
            for event in AIModelChangeEvent.objects.filter(
                workspace_id=workspace_id,
                created_at__date__gte=window_start,
            ).order_by("created_at")
        )

        return AIQualityOverviewView(
            workspace_id=str(workspace_id),
            window_days=days,
            series=tuple(series),
            model_changes=change_events,
        )
