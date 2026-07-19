"""Unit tests for the recurring-schedule next-run planner."""

from __future__ import annotations

from datetime import datetime, time, timezone as dt_tz

import pytest

from components.workflow.domain.services.schedule_planner import compute_next_run

pytestmark = pytest.mark.unit


def _utc(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=dt_tz.utc)


class TestDaily:
    def test_same_day_when_time_still_ahead(self):
        nxt = compute_next_run(
            cadence="daily", run_time=time(9, 0), after=_utc(2026, 6, 1, 8, 0)
        )
        assert nxt == _utc(2026, 6, 1, 9, 0)

    def test_next_day_when_time_passed(self):
        nxt = compute_next_run(
            cadence="daily", run_time=time(9, 0), after=_utc(2026, 6, 1, 10, 0)
        )
        assert nxt == _utc(2026, 6, 2, 9, 0)

    def test_exactly_at_time_rolls_forward(self):
        # Strictly-after: a fire exactly at run_time advances to the next day.
        nxt = compute_next_run(
            cadence="daily", run_time=time(9, 0), after=_utc(2026, 6, 1, 9, 0)
        )
        assert nxt == _utc(2026, 6, 2, 9, 0)


class TestWeekly:
    def test_picks_next_matching_weekday(self):
        # Wednesday = 2; result must land on a Wednesday in the future.
        after = _utc(2026, 6, 1, 12, 0)
        nxt = compute_next_run(
            cadence="weekly",
            run_time=time(9, 0),
            after=after,
            days_of_week=[2],
        )
        assert nxt > after
        assert nxt.weekday() == 2
        assert (nxt.hour, nxt.minute) == (9, 0)

    def test_multiple_days_picks_soonest(self):
        after = _utc(2026, 6, 1, 12, 0)
        nxt = compute_next_run(
            cadence="weekly",
            run_time=time(9, 0),
            after=after,
            days_of_week=[0, 2, 4],  # Mon/Wed/Fri
        )
        assert nxt > after
        assert nxt.weekday() in {0, 2, 4}


class TestMonthly:
    def test_this_month_when_day_ahead(self):
        nxt = compute_next_run(
            cadence="monthly",
            run_time=time(9, 0),
            after=_utc(2026, 6, 1),
            day_of_month=15,
        )
        assert nxt == _utc(2026, 6, 15, 9, 0)

    def test_next_month_when_day_passed(self):
        nxt = compute_next_run(
            cadence="monthly",
            run_time=time(9, 0),
            after=_utc(2026, 6, 20),
            day_of_month=15,
        )
        assert nxt == _utc(2026, 7, 15, 9, 0)

    def test_year_rolls_over_in_december(self):
        nxt = compute_next_run(
            cadence="monthly",
            run_time=time(9, 0),
            after=_utc(2026, 12, 20),
            day_of_month=15,
        )
        assert nxt == _utc(2027, 1, 15, 9, 0)

    def test_day_capped_at_28(self):
        nxt = compute_next_run(
            cadence="monthly",
            run_time=time(9, 0),
            after=_utc(2026, 2, 1),
            day_of_month=31,
        )
        assert nxt.day == 28


class TestTimezone:
    def test_run_time_is_local(self):
        # 09:00 America/New_York in June (EDT, UTC-4) == 13:00 UTC.
        nxt = compute_next_run(
            cadence="daily",
            run_time=time(9, 0),
            after=_utc(2026, 6, 1, 0, 0),
            timezone="America/New_York",
        )
        assert nxt == _utc(2026, 6, 1, 13, 0)


class TestInterval:
    def test_every_six_hours_advances_by_interval(self):
        nxt = compute_next_run(
            cadence="interval",
            after=_utc(2026, 6, 1, 8, 0),
            interval_minutes=360,
        )
        assert nxt == _utc(2026, 6, 1, 14, 0)

    def test_interval_ignores_run_time_and_timezone(self):
        # Interval is anchored purely to `after` — no fixed time-of-day.
        nxt = compute_next_run(
            cadence="interval",
            after=_utc(2026, 6, 1, 23, 30),
            interval_minutes=60,
            timezone="America/New_York",
        )
        assert nxt == _utc(2026, 6, 2, 0, 30)

    def test_interval_is_floored_to_minimum(self):
        # Anything below the floor is clamped so the per-minute Beat sweep is
        # never asked to fire faster than it ticks.
        nxt = compute_next_run(
            cadence="interval",
            after=_utc(2026, 6, 1, 0, 0),
            interval_minutes=1,
        )
        assert nxt == _utc(2026, 6, 1, 0, 15)


class TestGuards:
    def test_unknown_cadence_raises(self):
        with pytest.raises(ValueError):
            compute_next_run(
                cadence="hourly", run_time=time(9, 0), after=_utc(2026, 6, 1)
            )

    def test_fixed_cadence_without_run_time_raises(self):
        with pytest.raises(ValueError):
            compute_next_run(cadence="daily", after=_utc(2026, 6, 1))

    def test_naive_after_is_treated_as_utc(self):
        nxt = compute_next_run(
            cadence="daily",
            run_time=time(9, 0),
            after=datetime(2026, 6, 1, 8, 0),  # naive
        )
        assert nxt == _utc(2026, 6, 1, 9, 0)
