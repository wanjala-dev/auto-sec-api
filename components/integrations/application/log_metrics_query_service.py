"""Read side of the security-metric buckets — deterministic aggregates.

The single application entrypoint the ``log_analytics_agent`` tools call
("chat with the logs", posture vision §3.2). Counting/trend questions are
answered here with aggregates over ``LogMetricBucket`` rows — NEVER via RAG,
never via an LLM. The agent may only narrate what these functions return.

Layering: this module is framework-free orchestration; the ORM aggregation
lives in ``infrastructure/repositories/log_metric_bucket_repository.py``
(the application layer never imports ``django.*``). Bounded-context
boundary: the agents-context tools import ONLY this application module,
same as the sibling log services.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from components.integrations.application.log_metrics_service import (
    classify_trend_from_hourly,
    normalize_metric,
)

logger = logging.getLogger(__name__)

VALID_GROUP_BYS = ("service", "source", "day", "hour")
# Hard cap on rows returned to a caller — buckets are hourly, so a 90-day
# hourly grouping would otherwise ship 2 000+ rows into an LLM prompt.
MAX_ROWS = 200


def _window_hours(window_days: int | None, window_hours: int | None) -> int:
    if window_hours:
        return max(int(window_hours), 1)
    return max(int(window_days or 7), 1) * 24


def _since(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def query_metric(
    workspace_id,
    metric,
    *,
    window_days: int | None = None,
    window_hours: int | None = None,
    group_by: str | None = None,
    limit: int = 50,
) -> dict:
    """Aggregate one metric over the window, optionally grouped.

    Returns ``{"metric", "window_hours", "total", "group_by", "rows"}`` where
    ``rows`` is ``[]`` for an ungrouped total. Raises the shared-kernel
    ``ValidationError`` (a ``ValueError`` subclass) on an unknown metric or
    group_by — callers surface the message to the LLM.
    """
    from components.integrations.infrastructure.repositories import log_metric_bucket_repository as repo

    metric = normalize_metric(metric)
    if group_by is not None and group_by not in VALID_GROUP_BYS:
        from components.shared_kernel.domain.errors import ValidationError

        raise ValidationError(f"Unknown group_by {group_by!r}. Valid: {', '.join(VALID_GROUP_BYS)}.")
    hours = _window_hours(window_days, window_hours)
    limit = min(max(int(limit), 1), MAX_ROWS)
    since = _since(hours)

    total = repo.sum_total(workspace_id, metric, since)
    rows: list[dict] = []
    if group_by in ("service", "source"):
        rows = repo.counts_by_field(workspace_id, metric, since, group_by, limit)
    elif group_by == "day":
        rows = repo.counts_by_day(workspace_id, metric, since, limit)
    elif group_by == "hour":
        rows = [
            {"hour": hour.isoformat(), "count": count}
            for hour, count in repo.counts_by_hour(workspace_id, metric, since, limit).items()
        ]

    return {"metric": metric, "window_hours": hours, "total": total, "group_by": group_by, "rows": rows}


def classify_trend(
    workspace_id,
    metric,
    *,
    window_days: int | None = None,
    window_hours: int | None = None,
) -> dict:
    """Spike vs sustained vs quiet over the hourly buckets — the DDoS-shaped
    question, answered deterministically with the evidence numbers included."""
    from components.integrations.infrastructure.repositories import log_metric_bucket_repository as repo

    metric = normalize_metric(metric)
    hours = _window_hours(window_days, window_hours)
    hourly = repo.counts_by_hour(workspace_id, metric, _since(hours))
    result = classify_trend_from_hourly(hourly, hours)
    return {"metric": metric, "window_hours": hours, **result}


def top_sources(
    workspace_id, metric, *, window_days: int | None = None, window_hours: int | None = None, limit: int = 10
) -> dict:
    """Top attack sources (derived IPs) for a metric — "where did it come from"."""
    result = query_metric(
        workspace_id,
        metric,
        window_days=window_days,
        window_hours=window_hours,
        group_by="source",
        limit=limit,
    )
    return {
        "metric": result["metric"],
        "window_hours": result["window_hours"],
        "total": result["total"],
        "sources": result["rows"],
    }
