"""Resolve chart series data for a newsletter draft.

Today: a single donations-over-time line chart bucketed by week, ending
on the period_end date. Future iterations add recipients-growth and
events-calendar series; the contract returned here is the same shape
the FE renderer expects.

Framework-free: the actual weekly-totals aggregation lives behind
``DonationWeeklyTotalsReadPort`` so the domain layer never sees the
ORM. The caller injects the concrete adapter.
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from components.content.application.ports.donation_weekly_totals_read_port import (
        DonationWeeklyTotalsReadPort,
    )

logger = logging.getLogger(__name__)


WEEKS_BACK = 12


def _week_buckets(period_end: datetime.date) -> list[datetime.date]:
    """Return the last 12 week-start dates (Mondays) ending on the week
    that contains ``period_end``.
    """
    week_end_monday = period_end - datetime.timedelta(days=period_end.weekday())
    return [
        week_end_monday - datetime.timedelta(weeks=i)
        for i in range(WEEKS_BACK - 1, -1, -1)
    ]


def donations_over_time(
    *,
    workspace_id: UUID,
    period_end: datetime.date | None,
    repository: "DonationWeeklyTotalsReadPort",
) -> dict[str, Any] | None:
    """Return chart payload for the donations-over-time line series.

    Returns ``None`` when there's no donation data to plot — the caller
    drops the chart block from the tree so we don't render an empty
    axis.
    """
    if period_end is None:
        period_end = datetime.date.today()

    try:
        buckets = _week_buckets(period_end)
        window_start = buckets[0]
        # Include the full last week — week-truncation snaps to Mondays
        # so the upper bound is the Monday after period_end's week.
        window_end_exclusive = buckets[-1] + datetime.timedelta(weeks=1)

        by_week = repository.fetch_weekly_totals(
            workspace_id=workspace_id,
            window_start=window_start,
            window_end_exclusive=window_end_exclusive,
        )

        points = []
        for bucket in buckets:
            total = by_week.get(bucket, Decimal(0))
            points.append(
                {
                    "x": bucket.isoformat(),
                    "y": float(total),
                }
            )

        if all(p["y"] == 0 for p in points):
            return None

        return {
            "title": "Donations — last 12 weeks",
            "x_label": "Week starting",
            "y_label": "Donations ($)",
            "chart_type": "line",
            "series": [
                {
                    "label": "Donations",
                    "points": points,
                }
            ],
        }
    except Exception:  # noqa: BLE001
        logger.exception(
            "donations-over-time chart resolver failed for workspace_id=%s",
            workspace_id,
        )
        return None
