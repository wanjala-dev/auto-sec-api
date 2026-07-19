"""Unit tests for ``MeasureIndexFreshnessUseCase`` — the SLO core.

The use case is pure: it takes two latest-* values and a sample
time, computes lag, decides SLA compliance. No DB, no Celery. The
adapters are tested separately under ``tests/integration/``.

Four cases mapped to tests:

1. No events at all → workspace fresh (lag = 0).
2. Events exist, no index → lag = sample_time − event_time.
3. Index newer than event → workspace fully fresh (lag = 0).
4. Event newer than index → lag = event − index, in seconds.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from components.knowledge.application.ports.workspace_event_latest_port import (
    WorkspaceEventLatestPort,
)
from components.knowledge.application.ports.workspace_index_latest_port import (
    WorkspaceIndexLatestPort,
)
from components.knowledge.application.use_cases.measure_index_freshness_use_case import (
    DEFAULT_SLA_TARGET_SECONDS,
    MeasureIndexFreshnessUseCase,
)


@dataclass
class _FakeEventPort(WorkspaceEventLatestPort):
    value: Optional[datetime] = None

    def latest_event_time(self, *, workspace_id):  # noqa: D401
        return self.value


@dataclass
class _FakeIndexPort(WorkspaceIndexLatestPort):
    value: Optional[datetime] = None

    def latest_index_time(self, *, workspace_id):  # noqa: D401
        return self.value


def _utc(year, month, day, h=0, m=0, s=0):
    return datetime(year, month, day, h, m, s, tzinfo=timezone.utc)


class TestNoEventsCase:
    def test_no_events_no_index_lag_is_zero(self):
        """A freshly-created empty workspace is fresh by definition."""
        uc = MeasureIndexFreshnessUseCase(
            event_latest_port=_FakeEventPort(value=None),
            index_latest_port=_FakeIndexPort(value=None),
        )
        sample = uc.execute(
            workspace_id="w-1",
            sample_time=_utc(2026, 6, 11, 12, 0, 0),
        )
        assert sample.lag_seconds == 0
        assert sample.sla_met is True
        assert sample.has_events is False
        assert sample.has_index is False

    def test_no_events_with_index_lag_is_zero(self):
        """Indexed workspace with no events since indexing is fresh.
        The index is ahead; nothing to catch up on."""
        uc = MeasureIndexFreshnessUseCase(
            event_latest_port=_FakeEventPort(value=None),
            index_latest_port=_FakeIndexPort(value=_utc(2026, 6, 11, 11, 0)),
        )
        sample = uc.execute(
            workspace_id="w-1",
            sample_time=_utc(2026, 6, 11, 12, 0),
        )
        assert sample.lag_seconds == 0
        assert sample.sla_met is True


class TestEventsNoIndexCase:
    def test_events_no_index_lag_is_distance_from_now(self):
        """Workspace has events but has never been indexed —
        lag is the full distance from sample_time. This row
        will fail the SLO, which is the correct signal."""
        uc = MeasureIndexFreshnessUseCase(
            event_latest_port=_FakeEventPort(
                value=_utc(2026, 6, 11, 11, 30)
            ),
            index_latest_port=_FakeIndexPort(value=None),
        )
        sample = uc.execute(
            workspace_id="w-1",
            sample_time=_utc(2026, 6, 11, 12, 0),
        )
        assert sample.lag_seconds == 30 * 60  # 30 min
        assert sample.sla_met is False  # default 10 min threshold
        assert sample.has_events is True
        assert sample.has_index is False


class TestIndexNewerThanEventCase:
    def test_index_newer_than_event_lag_is_zero(self):
        """The index already caught up. Workspace is fully fresh."""
        uc = MeasureIndexFreshnessUseCase(
            event_latest_port=_FakeEventPort(
                value=_utc(2026, 6, 11, 11, 0)
            ),
            index_latest_port=_FakeIndexPort(
                value=_utc(2026, 6, 11, 11, 30)
            ),
        )
        sample = uc.execute(
            workspace_id="w-1",
            sample_time=_utc(2026, 6, 11, 12, 0),
        )
        assert sample.lag_seconds == 0
        assert sample.sla_met is True


class TestEventNewerThanIndexCase:
    def test_event_newer_lag_is_their_difference(self):
        """The typical write-storm case. Lag = event - index."""
        uc = MeasureIndexFreshnessUseCase(
            event_latest_port=_FakeEventPort(
                value=_utc(2026, 6, 11, 11, 55)
            ),
            index_latest_port=_FakeIndexPort(
                value=_utc(2026, 6, 11, 11, 50)
            ),
        )
        sample = uc.execute(
            workspace_id="w-1",
            sample_time=_utc(2026, 6, 11, 12, 0),
        )
        assert sample.lag_seconds == 5 * 60  # 5 min
        assert sample.sla_met is True  # under 10 min threshold

    def test_event_well_past_threshold_marks_sla_miss(self):
        """Event 15 minutes ahead of index → SLO miss at default 10 min."""
        uc = MeasureIndexFreshnessUseCase(
            event_latest_port=_FakeEventPort(
                value=_utc(2026, 6, 11, 12, 0)
            ),
            index_latest_port=_FakeIndexPort(
                value=_utc(2026, 6, 11, 11, 45)
            ),
        )
        sample = uc.execute(
            workspace_id="w-1",
            sample_time=_utc(2026, 6, 11, 12, 5),
        )
        assert sample.lag_seconds == 15 * 60
        assert sample.sla_met is False


class TestThresholdOverride:
    def test_custom_threshold_changes_sla_decision(self):
        """A what-if at a tighter threshold marks the same lag
        differently — useful for ops planning."""
        uc = MeasureIndexFreshnessUseCase(
            event_latest_port=_FakeEventPort(
                value=_utc(2026, 6, 11, 12, 0)
            ),
            index_latest_port=_FakeIndexPort(
                value=_utc(2026, 6, 11, 11, 53)
            ),
        )
        # 7 minutes lag — passes 10 min threshold.
        sample = uc.execute(
            workspace_id="w-1",
            sample_time=_utc(2026, 6, 11, 12, 5),
        )
        assert sample.sla_met is True

        # Same lag — fails 5 min threshold.
        sample = uc.execute(
            workspace_id="w-1",
            sample_time=_utc(2026, 6, 11, 12, 5),
            sla_target_seconds=300,
        )
        assert sample.sla_met is False
        assert sample.sla_target_seconds == 300

    def test_records_target_on_sample(self):
        """Sample records the threshold it was scored against —
        so the IndexFreshnessSample row stays interpretable after
        the prod SLO retunes."""
        uc = MeasureIndexFreshnessUseCase(
            event_latest_port=_FakeEventPort(value=None),
            index_latest_port=_FakeIndexPort(value=None),
        )
        sample = uc.execute(
            workspace_id="w-1",
            sample_time=_utc(2026, 6, 11, 12, 0),
        )
        assert sample.sla_target_seconds == DEFAULT_SLA_TARGET_SECONDS


class TestSampleFrozen:
    def test_sample_is_immutable(self):
        """Frozen dataclass — the audit task can't mutate a sample
        between computing and persisting (common bug in batch
        loops where the same dict reference gets reused)."""
        import dataclasses

        uc = MeasureIndexFreshnessUseCase(
            event_latest_port=_FakeEventPort(value=None),
            index_latest_port=_FakeIndexPort(value=None),
        )
        sample = uc.execute(
            workspace_id="w-1",
            sample_time=_utc(2026, 6, 11, 12, 0),
        )
        try:
            sample.lag_seconds = 9999  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            return
        raise AssertionError("FreshnessSample must be frozen")
