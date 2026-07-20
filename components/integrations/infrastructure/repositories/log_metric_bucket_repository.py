"""ORM access for the hourly security-metric buckets.

The single place Django query expressions (``F``/``Sum``/``TruncDay``) touch
``LogMetricBucket`` — the application services
(``log_metrics_service`` / ``log_metrics_query_service``) stay framework-free
and delegate here (architecture rule: the application layer never imports
``django.*``; ORM queries live in infrastructure repositories).

Writes are row-count-safe: concurrent aggregators increment via ``F()``
expressions, never read-modify-write. Deterministic; no LLM ever writes here.
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import F, Sum
from django.db.models.functions import TruncDay

from infrastructure.persistence.integrations.models import LogMetricBucket


def upsert_bucket(
    connection,
    *,
    metric: str,
    service: str,
    source: str,
    bucket_start: datetime,
    count: int,
    sample_message: str,
) -> None:
    """Create the bucket row or atomically increment its count."""
    obj, created = LogMetricBucket.objects.get_or_create(
        connection=connection,
        metric=metric,
        service=service,
        source=source,
        bucket_start=bucket_start,
        defaults={
            "workspace_id": connection.workspace_id,
            "count": count,
            "sample_message": sample_message,
        },
    )
    if not created:
        LogMetricBucket.objects.filter(pk=obj.pk).update(count=F("count") + count)


def _window_qs(workspace_id, metric: str, since: datetime):
    return LogMetricBucket.objects.filter(workspace_id=workspace_id, metric=metric, bucket_start__gte=since)


def sum_total(workspace_id, metric: str, since: datetime) -> int:
    return _window_qs(workspace_id, metric, since).aggregate(total=Sum("count"))["total"] or 0


def counts_by_field(workspace_id, metric: str, since: datetime, field: str, limit: int) -> list[dict]:
    """Grouped counts by ``service`` or ``source`` (blank sources excluded)."""
    qs = _window_qs(workspace_id, metric, since)
    if field == "source":
        qs = qs.exclude(source="")
    rows = qs.values(field).annotate(total=Sum("count")).order_by("-total")[:limit]
    return [{field: r[field], "count": r["total"]} for r in rows]


def counts_by_day(workspace_id, metric: str, since: datetime, limit: int) -> list[dict]:
    rows = (
        _window_qs(workspace_id, metric, since)
        .annotate(day=TruncDay("bucket_start"))
        .values("day")
        .annotate(total=Sum("count"))
        .order_by("day")[:limit]
    )
    return [{"day": r["day"].date().isoformat(), "count": r["total"]} for r in rows]


def counts_by_hour(workspace_id, metric: str, since: datetime, limit: int | None = None) -> dict[datetime, int]:
    """Hourly totals keyed by bucket_start (buckets are already hour-truncated)."""
    rows = (
        _window_qs(workspace_id, metric, since)
        .values("bucket_start")
        .annotate(total=Sum("count"))
        .order_by("bucket_start")
    )
    if limit is not None:
        rows = rows[:limit]
    return {r["bucket_start"]: r["total"] for r in rows}
