"""Celery beat tasks that roll the WorkspaceAIUsage windows forward.

Both tasks are idempotent — they just stamp the current window
boundary onto the row and zero the counter. Safe to run as often as
once a minute; designed to run once at the start of each window.

These centralise window rollover so the increment path in
``OrmWorkspaceAIConfigAdapter.increment_workspace_usage`` can stay
simple (single ``F()`` update). The adapter also has a fallback
rollover branch for the edge case where a message arrives after
midnight UTC before this task has run.
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="ai.reset_daily_ai_usage_windows", ignore_result=True)
def reset_daily_ai_usage_windows() -> int:
    """Zero out the daily counter on rows where the window has rolled over.

    Returns the number of rows touched, so the Celery log shows how
    many workspaces were active in the last cycle.
    """
    # Import inside the task — Django app registry may not be ready
    # when the worker imports the module.
    from infrastructure.persistence.ai.aggregations.models import WorkspaceAIUsage

    today = timezone.now().date()
    rows = WorkspaceAIUsage.objects.exclude(daily_window_start=today)
    touched = rows.update(daily_messages_sent=0, daily_window_start=today)
    logger.info(
        "ai.reset_daily_ai_usage_windows touched=%s today=%s",
        touched,
        today.isoformat(),
    )
    return touched


@shared_task(name="ai.reset_monthly_ai_usage_windows", ignore_result=True)
def reset_monthly_ai_usage_windows() -> int:
    """Zero the monthly token + run counters on rows where the month rolled over.

    Tokens (cost guardrail) and runs (tier monetization lever) keep separate
    monthly windows, so each is rolled independently — a workspace that only
    consumed one dimension still gets the other reset cleanly.
    """
    from infrastructure.persistence.ai.aggregations.models import WorkspaceAIUsage

    month_start = timezone.now().date().replace(day=1)
    touched = (
        WorkspaceAIUsage.objects.exclude(monthly_window_start=month_start)
        .update(monthly_tokens_used=0, monthly_window_start=month_start)
    )
    runs_touched = (
        WorkspaceAIUsage.objects.exclude(monthly_runs_window_start=month_start)
        .update(monthly_runs_used=0, monthly_runs_window_start=month_start)
    )
    logger.info(
        "ai.reset_monthly_ai_usage_windows tokens_touched=%s runs_touched=%s month_start=%s",
        touched,
        runs_touched,
        month_start.isoformat(),
    )
    return touched + runs_touched
