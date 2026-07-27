"""Staleness logic — incl. the naive/aware datetime regression (USE_TZ=False).

The project runs ``USE_TZ=False``, so the ORM returns NAIVE ``computed_at``. An
earlier version compared it against an aware ``datetime.now(timezone.utc)`` and 500'd
with "can't subtract offset-naive and offset-aware datetimes". These tests pin the
mixed-awareness cases directly (independent of test-settings USE_TZ).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from components.findings.application.ports.attck_coverage_port import CoverageSnapshot
from components.findings.application.use_cases.get_attck_coverage_use_case import (
    GetAttckCoverageUseCase,
)

pytestmark = pytest.mark.unit


class _FakeStore:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def get(self, workspace_id):
        return self._snapshot


def _snap(computed_at):
    return CoverageSnapshot(coverage={"tactics": []}, technique_count=0, finding_count=0, computed_at=computed_at)


def _uc(computed_at):
    return GetAttckCoverageUseCase(store=_FakeStore(_snap(computed_at)))


_NAIVE_NOW = datetime(2026, 7, 27, 12, 0, 0)  # naive, as timezone.now() gives under USE_TZ=False


def test_naive_now_and_naive_computed_at_does_not_crash():
    snap, is_stale = _uc(_NAIVE_NOW - timedelta(seconds=600)).execute("ws", _NAIVE_NOW, ttl_seconds=300)
    assert is_stale is True  # 600s old > 300s TTL


def test_naive_now_vs_aware_computed_at_does_not_crash():
    aware_past = datetime(2026, 7, 27, 11, 50, tzinfo=UTC)  # 600s before naive_now (UTC)
    snap, is_stale = _uc(aware_past).execute("ws", _NAIVE_NOW, ttl_seconds=300)
    assert is_stale is True


def test_fresh_materialization_not_stale():
    snap, is_stale = _uc(_NAIVE_NOW - timedelta(seconds=10)).execute("ws", _NAIVE_NOW, ttl_seconds=300)
    assert is_stale is False


def test_unmaterialized_is_always_stale():
    snap, is_stale = _uc(None).execute("ws", _NAIVE_NOW)
    assert not snap.is_materialized
    assert is_stale is True
