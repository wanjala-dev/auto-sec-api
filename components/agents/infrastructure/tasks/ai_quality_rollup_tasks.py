"""Celery beat task that rolls raw AI telemetry into daily quality metrics.

Recomputes (never increments) the ``AIModelDailyMetric`` +
``AIWorkspaceDailyMetric`` rollups from the raw sources:

- ``DeepRunLog`` llm-call rows → per-(workspace, model, day) call
  counts, tokens, cost, latency p50/p95. The query filters on
  ``event_type='llm_call'`` so the existing ``(event_type, created_at)``
  index covers it.
- ``DeepRun`` rows → per-(workspace, day) run outcome counts.
- ``ConversationMessage`` (assistant role) + ``AgentResponseFeedback``
  → per-(workspace, day) message + thumbs counters. Workspace comes
  from ``Conversation.metadata['workspace_id']`` (the conversation
  model has no workspace FK), grouped in Python — acceptable for a
  background batch over a two-day window, never done on a request path.

Recompute-not-increment means the task is idempotent: re-running a day
converges on the same numbers, late votes / rating flips inside the
window are absorbed, and a one-off ``rollup_ai_quality_daily.delay(
days_back=90)`` backfills history from retained raw rows.

Percentiles are computed in Python per bucket (day×workspace×model
volumes are small) — keeps the task portable to the SQLite test DB,
which has no ``percentile_cont``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

DEFAULT_DAYS_BACK = 2  # today + yesterday — absorbs late rows around midnight


def _percentile(sorted_values: list[int], fraction: float) -> int | None:
    """Nearest-rank percentile over a pre-sorted list. None when empty."""
    if not sorted_values:
        return None
    index = max(0, min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1))))
    return int(sorted_values[index])


def _day_bounds(day) -> tuple[datetime, datetime]:
    """Aware UTC [start, end) datetimes for a calendar date."""
    tz = timezone.get_default_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def _rollup_model_metrics_for_day(day) -> int:
    """Recompute AIModelDailyMetric rows for one day. Returns rows written."""
    from infrastructure.persistence.ai.agents.models import DeepRunLog
    from infrastructure.persistence.ai.aggregations.models import AIModelDailyMetric

    start, end = _day_bounds(day)
    rows = (
        DeepRunLog.objects.filter(
            event_type="llm_call",
            created_at__gte=start,
            created_at__lt=end,
        )
        .exclude(model_used="")
        .exclude(deep_run__workspace_id=None)
        .values_list(
            "deep_run__workspace_id",
            "model_used",
            "prompt_tokens",
            "completion_tokens",
            "cost_usd",
            "latency_ms",
        )
        .iterator(chunk_size=500)
    )

    buckets: dict[tuple, dict] = defaultdict(
        lambda: {
            "llm_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": Decimal("0"),
            "latencies": [],
        }
    )
    for workspace_id, model, p_tokens, c_tokens, cost, latency in rows:
        bucket = buckets[(workspace_id, model)]
        bucket["llm_calls"] += 1
        bucket["prompt_tokens"] += p_tokens or 0
        bucket["completion_tokens"] += c_tokens or 0
        bucket["cost_usd"] += cost or Decimal("0")
        if latency is not None:
            bucket["latencies"].append(latency)

    metric_rows = []
    for (workspace_id, model), bucket in buckets.items():
        latencies = sorted(bucket["latencies"])
        metric_rows.append(
            AIModelDailyMetric(
                workspace_id=workspace_id,
                date=day,
                model_used=model,
                llm_calls=bucket["llm_calls"],
                prompt_tokens=bucket["prompt_tokens"],
                completion_tokens=bucket["completion_tokens"],
                cost_usd=bucket["cost_usd"],
                latency_p50_ms=_percentile(latencies, 0.50),
                latency_p95_ms=_percentile(latencies, 0.95),
            )
        )

    with transaction.atomic():
        # Delete-then-recreate keeps the recompute exact: buckets that
        # vanished from the raw data (e.g. a deleted run) don't leave
        # stale rollup rows behind. MVCC keeps concurrent readers on the
        # pre-transaction snapshot.
        AIModelDailyMetric.objects.filter(date=day).delete()
        AIModelDailyMetric.objects.bulk_create(metric_rows)
    return len(metric_rows)


def _rollup_workspace_metrics_for_day(day) -> int:
    """Recompute AIWorkspaceDailyMetric rows for one day. Returns rows written."""
    from infrastructure.persistence.ai.agents.models import DeepRun
    from infrastructure.persistence.ai.aggregations.models import AIWorkspaceDailyMetric
    from infrastructure.persistence.ai.conversations.models import (
        AgentResponseFeedback,
        ConversationMessage,
    )

    start, end = _day_bounds(day)
    buckets: dict[str, dict] = defaultdict(
        lambda: {
            "runs_total": 0,
            "runs_completed": 0,
            "runs_failed": 0,
            "assistant_messages": 0,
            "feedback_up": 0,
            "feedback_down": 0,
        }
    )

    run_rows = (
        DeepRun.objects.filter(created_at__gte=start, created_at__lt=end)
        .exclude(workspace_id=None)
        .values_list("workspace_id", "status")
        .iterator(chunk_size=500)
    )
    for workspace_id, run_status in run_rows:
        bucket = buckets[str(workspace_id)]
        bucket["runs_total"] += 1
        if run_status == DeepRun.STATUS_COMPLETED:
            bucket["runs_completed"] += 1
        elif run_status == DeepRun.STATUS_FAILED:
            bucket["runs_failed"] += 1

    # Conversation carries workspace only in metadata JSON — group in
    # Python. Background batch over one day; never a request-path read.
    message_rows = (
        ConversationMessage.objects.filter(
            role="assistant",
            created_at__gte=start,
            created_at__lt=end,
        )
        .values_list("conversation__metadata__workspace_id", flat=True)
        .iterator(chunk_size=500)
    )
    for workspace_id in message_rows:
        if workspace_id:
            buckets[str(workspace_id)]["assistant_messages"] += 1

    feedback_rows = (
        AgentResponseFeedback.objects.filter(
            created_at__gte=start,
            created_at__lt=end,
        )
        .values_list("message__conversation__metadata__workspace_id", "rating")
        .iterator(chunk_size=500)
    )
    for workspace_id, rating in feedback_rows:
        if not workspace_id:
            continue
        if rating == AgentResponseFeedback.RATING_UP:
            buckets[str(workspace_id)]["feedback_up"] += 1
        elif rating == AgentResponseFeedback.RATING_DOWN:
            buckets[str(workspace_id)]["feedback_down"] += 1

    metric_rows = [
        AIWorkspaceDailyMetric(workspace_id=workspace_id, date=day, **counters)
        for workspace_id, counters in buckets.items()
    ]

    with transaction.atomic():
        AIWorkspaceDailyMetric.objects.filter(date=day).delete()
        AIWorkspaceDailyMetric.objects.bulk_create(metric_rows)
    return len(metric_rows)


@shared_task(name="ai.rollup_ai_quality_daily", ignore_result=True)
def rollup_ai_quality_daily(days_back: int = DEFAULT_DAYS_BACK) -> int:
    """Recompute the AI quality rollups for the trailing ``days_back`` days.

    Beat runs it hourly with the default window (today + yesterday);
    call it once with a larger ``days_back`` to backfill history.
    Returns the total number of rollup rows written.
    """
    days_back = max(1, int(days_back))
    today = timezone.now().date()
    written = 0
    for offset in range(days_back):
        day = today - timedelta(days=offset)
        model_rows = _rollup_model_metrics_for_day(day)
        workspace_rows = _rollup_workspace_metrics_for_day(day)
        written += model_rows + workspace_rows
        logger.info(
            "ai.rollup_ai_quality_daily day=%s model_rows=%s workspace_rows=%s",
            day.isoformat(),
            model_rows,
            workspace_rows,
        )
    return written
