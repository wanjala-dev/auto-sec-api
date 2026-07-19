"""Compute the next fire time for a recurring workflow schedule.

Pure and timezone-aware. A schedule fires at a fixed local time-of-day on a
daily / weekly / monthly cadence; ``compute_next_run`` returns the next aware
UTC datetime strictly AFTER ``after``. The Beat sweep stores this on
``WorkflowSchedule.next_run_at`` and advancing it is what makes a fire
idempotent against missed or retried ticks.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone as dt_timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

# Monthly fires are capped at the 28th so every month has the day (no skipped
# months for Feb / 30-day months).
MAX_DAY_OF_MONTH = 28

# Interval cadence is floored so the per-minute Beat sweep is never asked to
# fire faster than it ticks. Mirrors WorkflowSchedule.MIN_INTERVAL_MINUTES.
MIN_INTERVAL_MINUTES = 15


def _combine(date_part, run_time: time, tz: ZoneInfo) -> datetime:
    return datetime(
        date_part.year,
        date_part.month,
        date_part.day,
        run_time.hour,
        run_time.minute,
        run_time.second,
        tzinfo=tz,
    )


def compute_next_run(
    *,
    cadence: str,
    run_time: Optional[time] = None,
    after: datetime,
    timezone: str = "UTC",
    days_of_week: Optional[List[int]] = None,
    day_of_month: Optional[int] = None,
    interval_minutes: Optional[int] = None,
) -> datetime:
    """Return the next fire time (aware UTC) strictly after ``after``.

    - interval: every ``interval_minutes`` minutes from ``after`` (no fixed
      time-of-day; floored at ``MIN_INTERVAL_MINUTES``).
    - daily: every day at ``run_time``.
    - weekly: on each weekday in ``days_of_week`` (0=Monday .. 6=Sunday).
    - monthly: on ``day_of_month`` (1-28; values >28 are capped).
    """
    if after.tzinfo is None:
        after = after.replace(tzinfo=dt_timezone.utc)

    if cadence == "interval":
        minutes = max(MIN_INTERVAL_MINUTES, int(interval_minutes or 0))
        return (after + timedelta(minutes=minutes)).astimezone(dt_timezone.utc)

    if run_time is None:
        raise ValueError(f"run_time is required for cadence {cadence!r}")

    tz = ZoneInfo(timezone)
    after_local = after.astimezone(tz)

    if cadence == "daily":
        candidate = _combine(after_local.date(), run_time, tz)
        if candidate <= after_local:
            candidate += timedelta(days=1)
        return candidate.astimezone(dt_timezone.utc)

    if cadence == "weekly":
        days = sorted({int(d) for d in (days_of_week or []) if 0 <= int(d) <= 6})
        if not days:
            # No days selected — fall back to the same weekday as `after`.
            days = [after_local.weekday()]
        # Scan the next 8 days; the first matching weekday whose time is in the
        # future wins (8 covers wrap-around to next week).
        for offset in range(0, 8):
            day = after_local.date() + timedelta(days=offset)
            if day.weekday() in days:
                candidate = _combine(day, run_time, tz)
                if candidate > after_local:
                    return candidate.astimezone(dt_timezone.utc)
        # Unreachable for valid input, but stay total.
        return _combine(
            after_local.date() + timedelta(days=7), run_time, tz
        ).astimezone(dt_timezone.utc)

    if cadence == "monthly":
        dom = min(int(day_of_month or 1), MAX_DAY_OF_MONTH)
        year, month = after_local.year, after_local.month
        candidate = _combine(
            after_local.date().replace(day=dom), run_time, tz
        )
        if candidate <= after_local:
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1
            candidate = _combine(
                after_local.date().replace(year=year, month=month, day=dom),
                run_time,
                tz,
            )
        return candidate.astimezone(dt_timezone.utc)

    raise ValueError(f"unknown cadence: {cadence!r}")
