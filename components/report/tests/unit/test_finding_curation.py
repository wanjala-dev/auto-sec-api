"""Unit tests for deterministic finding curation (dedup + §4 cap).

Pure domain — no DB, no Django. Exercises the two curation steps that turn a
raw board dump into a curated deliverable:
  * ``dedupe_findings`` — collapse near-identical findings, count occurrences.
  * ``select_featured`` — which deduped findings get a full technical section.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from components.report.domain.services import finding_section_builder as fsb
from components.report.domain.services.finding_curation import (
    dedupe_findings,
    finding_signature,
    select_featured,
)

pytestmark = pytest.mark.unit


def _finding(
    *,
    severity="high",
    service="celery_worker",
    signal="ERROR in celery_worker",
    title="t",
    action="log_watch",
    created=None,
):
    return {
        "id": title,
        "title": title,
        "created_at": created or datetime(2026, 1, 1, tzinfo=UTC),
        "metadata": {
            "severity": severity,
            "action_type": action,
            "payload": {"service": service, "signal": signal},
        },
    }


class TestSignature:
    def test_uuid_and_digits_normalised_out(self):
        a = _finding(title="Task recommendations.refresh[b062f7bb-448c-461a-99c3-d9ec8479fb0c]")
        b = _finding(title="Task recommendations.refresh[be912950-24c3-48a8-a99a-c723eda955ac]")
        # Same service/signal/severity — the varying task uuid in the title must
        # not split them: the signal is the discriminator.
        assert finding_signature(a) == finding_signature(b)

    def test_line_count_number_normalised(self):
        a = _finding(
            action="log_optimization", service="pgbouncer", signal="pgbouncer produced 212 log lines this window"
        )
        b = _finding(
            action="log_optimization", service="pgbouncer", signal="pgbouncer produced 237 log lines this window"
        )
        assert finding_signature(a) == finding_signature(b)

    def test_different_service_is_distinct(self):
        a = _finding(service="celery_worker", signal="ERROR in celery_worker")
        b = _finding(service="web", signal="ERROR in web")
        assert finding_signature(a) != finding_signature(b)

    def test_different_severity_is_distinct(self):
        assert finding_signature(_finding(severity="high")) != finding_signature(_finding(severity="medium"))


class TestDedupe:
    def test_collapses_cluster_with_occurrence_count(self):
        raw = [_finding(title=f"task-{i}") for i in range(320)]
        curated = dedupe_findings(raw)
        assert len(curated) == 1
        assert curated[0].occurrences == 320

    def test_keeps_distinct_findings_separate(self):
        raw = [
            _finding(service="celery_worker", signal="ERROR in celery_worker"),
            _finding(service="web", signal="ERROR in web"),
            _finding(service="nginx", signal="INFO in nginx", severity="medium"),
        ]
        curated = dedupe_findings(raw)
        assert len(curated) == 3
        assert all(c.occurrences == 1 for c in curated)

    def test_tracks_first_and_last_seen(self):
        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        raw = [
            _finding(title="a", created=t0),
            _finding(title="b", created=t0 + timedelta(days=3)),
            _finding(title="c", created=t0 + timedelta(days=1)),
        ]
        curated = dedupe_findings(raw)
        assert len(curated) == 1
        assert curated[0].first_seen == t0
        assert curated[0].last_seen == t0 + timedelta(days=3)

    def test_empty_input(self):
        assert dedupe_findings([]) == ()


class TestSelectFeatured:
    def _technicals(self, bands):
        out = []
        for i, band in enumerate(bands, start=1):
            out.append(fsb.build_technical_finding(_finding(severity=band, title=f"t{i}"), fid=f"F-{i:02d}"))
        return tuple(out)

    def test_high_severity_always_featured_even_beyond_cap(self):
        techs = self._technicals(["high"] * 30)  # 30 highs, cap 25
        featured = select_featured(techs, full_detail_bands=("critical", "high"), max_count=25)
        # A report must never bury a high — all 30 stay fully detailed.
        assert len(featured) == 30

    def test_lower_bands_capped(self):
        techs = self._technicals(["high", "high"] + ["low"] * 40)
        featured = select_featured(techs, full_detail_bands=("critical", "high"), max_count=10)
        # 2 highs always in + fill to 10 with lows = 10 total.
        assert len(featured) == 10
        assert sum(1 for t in featured if t.severity.band == "high") == 2
        assert sum(1 for t in featured if t.severity.band == "low") == 8

    def test_preserves_order_and_fids(self):
        techs = self._technicals(["high", "low", "low"])
        featured = select_featured(techs, full_detail_bands=("high",), max_count=2)
        assert [t.fid for t in featured] == ["F-01", "F-02"]

    def test_all_featured_when_under_cap(self):
        techs = self._technicals(["high", "medium", "low"])
        featured = select_featured(techs, full_detail_bands=("critical", "high"), max_count=25)
        assert len(featured) == 3
