"""Celery beat task that rolls raw AI-action telemetry into daily rollups.

Recomputes (never increments) the ``AiActionDailyRollup`` read model from
the raw sources:

- ``DeepRun`` rows → per-(workspace, day) run outcome counts
  (total / completed / failed).
- ``DeepRunLog`` ``tool_observation`` rows → per-(workspace, day) tool-call
  counts. The query filters on ``event_type`` so the existing
  ``(event_type, created_at)`` index covers it.
- ``DeepRunLog`` ``llm_call`` rows → per-(workspace, day) token +
  cost totals (``prompt_tokens`` → ``tokens_input``,
  ``completion_tokens`` → ``tokens_output``, ``cost_usd`` summed).

Recompute-not-increment means the task is idempotent: re-running a day
converges on the same numbers, late-arriving rows inside the window are
absorbed, and the ``backfill_ai_action_rollups`` management command
rebuilds history from retained raw rows. Same contract (and same
day-delete + bulk-create write pattern) as the sibling
``ai.rollup_ai_quality_daily`` task.

The beat schedule runs it shortly after midnight with the default window
(yesterday); the posture-dashboard governance charts read ONLY these
rollup rows for their daily cost/runs series — never the raw log.
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

# Yesterday only — the day is complete, so one recompute converges. The
# backfill command widens the window when history is needed.
DEFAULT_DAYS_BACK = 1


def _day_bounds(day) -> tuple[datetime, datetime]:
    """Aware [start, end) datetimes for a calendar date."""
    tz = timezone.get_default_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def _empty_bucket() -> dict:
    return {
        "runs_total": 0,
        "runs_completed": 0,
        "runs_failed": 0,
        "tool_calls": 0,
        "tokens_input": 0,
        "tokens_output": 0,
        "cost_usd": Decimal("0"),
    }


def rollup_ai_actions_for_day(day) -> int:
    """Recompute AiActionDailyRollup rows for one day. Returns rows written."""
    from infrastructure.persistence.ai.agents.models import (
        AiActionDailyRollup,
        DeepRun,
        DeepRunLog,
    )

    start, end = _day_bounds(day)
    buckets: dict[str, dict] = defaultdict(_empty_bucket)

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

    tool_rows = (
        DeepRunLog.objects.filter(
            event_type="tool_observation",
            created_at__gte=start,
            created_at__lt=end,
        )
        .exclude(deep_run__workspace_id=None)
        .values_list("deep_run__workspace_id", flat=True)
        .iterator(chunk_size=500)
    )
    for workspace_id in tool_rows:
        buckets[str(workspace_id)]["tool_calls"] += 1

    llm_rows = (
        DeepRunLog.objects.filter(
            event_type="llm_call",
            created_at__gte=start,
            created_at__lt=end,
        )
        .exclude(deep_run__workspace_id=None)
        .values_list(
            "deep_run__workspace_id",
            "prompt_tokens",
            "completion_tokens",
            "cost_usd",
        )
        .iterator(chunk_size=500)
    )
    for workspace_id, prompt_tokens, completion_tokens, cost_usd in llm_rows:
        bucket = buckets[str(workspace_id)]
        bucket["tokens_input"] += int(prompt_tokens or 0)
        bucket["tokens_output"] += int(completion_tokens or 0)
        bucket["cost_usd"] += Decimal(cost_usd or 0)

    rollup_rows = [
        AiActionDailyRollup(workspace_id=workspace_id, date=day, **counters)
        for workspace_id, counters in buckets.items()
    ]

    with transaction.atomic():
        AiActionDailyRollup.objects.filter(date=day).delete()
        AiActionDailyRollup.objects.bulk_create(rollup_rows)
    return len(rollup_rows)


@shared_task(name="ai.rollup_ai_action_daily", ignore_result=True)
def rollup_ai_action_daily(days_back: int = DEFAULT_DAYS_BACK, include_today: bool = False) -> int:
    """Recompute the AI-action rollups for the trailing ``days_back`` days.

    Beat runs it daily with the default window (yesterday only — the day
    is complete). ``include_today`` widens the window to the current
    (partial) day — the backfill command uses it so a fresh install has
    a today series immediately. Returns the total rows written.
    """
    days_back = max(1, int(days_back))
    today = timezone.now().date()
    written = 0
    first_offset = 0 if include_today else 1
    for offset in range(first_offset, first_offset + days_back):
        day = today - timedelta(days=offset)
        rows = rollup_ai_actions_for_day(day)
        written += rows
        logger.info("ai.rollup_ai_action_daily day=%s rows=%s", day.isoformat(), rows)
    return written
