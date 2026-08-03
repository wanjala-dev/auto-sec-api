"""Integration: refresh lands a dated snapshot; the read port maps CVE → EPSS/KEV.

Uses fake feed adapters (no network) with the real ``VulnSnapshotRepository`` +
``VulnIntelReader`` so the persistence + read path is exercised end to end (ADR 0013 D2).
"""

from __future__ import annotations

from datetime import date

import pytest

from components.vuln_intel.application.ports.vuln_feed_port import EpssFeedPort, KevFeedPort
from components.vuln_intel.application.use_cases.refresh_feeds_use_case import RefreshFeedsUseCase
from components.vuln_intel.domain.value_objects.feed_snapshot import (
    EpssFeedSnapshot,
    EpssRecord,
    KevFeedSnapshot,
    KevRecord,
)
from components.vuln_intel.infrastructure.repositories.vuln_intel_read_repository import VulnIntelReader
from components.vuln_intel.infrastructure.repositories.vuln_snapshot_repository import VulnSnapshotRepository

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class _FakeEpssFeed(EpssFeedPort):
    def __init__(self, snapshot: EpssFeedSnapshot) -> None:
        self._snapshot = snapshot

    def fetch(self) -> EpssFeedSnapshot:
        return self._snapshot


class _FakeKevFeed(KevFeedPort):
    def __init__(self, snapshot: KevFeedSnapshot) -> None:
        self._snapshot = snapshot

    def fetch(self) -> KevFeedSnapshot:
        return self._snapshot


class _CapturingPublisher:
    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


def _epss(score_date: date) -> EpssFeedSnapshot:
    return EpssFeedSnapshot(
        score_date=score_date,
        model_version="v2025.03.14",
        records=(
            EpssRecord(cve="CVE-2021-44228", epss=0.94398, percentile=0.99931),
            EpssRecord(cve="CVE-2024-3094", epss=0.0004, percentile=0.05),
        ),
    )


def _kev(version: str, cves: tuple[str, ...]) -> KevFeedSnapshot:
    return KevFeedSnapshot(
        catalog_version=version,
        records=tuple(KevRecord(cve=c, date_added=date(2021, 12, 10)) for c in cves),
    )


def _run_refresh(epss_snap, kev_snap, publisher=None):
    return RefreshFeedsUseCase(
        epss_feed=_FakeEpssFeed(epss_snap),
        kev_feed=_FakeKevFeed(kev_snap),
        store=VulnSnapshotRepository(),
        event_publisher=publisher,
    ).execute()


class TestRefreshAndRead:
    def test_refresh_lands_dated_snapshot_and_reader_maps_cve(self):
        publisher = _CapturingPublisher()
        result = _run_refresh(_epss(date(2026, 8, 3)), _kev("2026.08.01", ("CVE-2021-44228",)), publisher)

        assert result.epss_score_date == "2026-08-03"
        assert result.epss_records == 2
        assert result.kev_catalog_version == "2026.08.01"
        assert not result.errors

        reader = VulnIntelReader()
        log4shell = reader.epss("CVE-2021-44228")
        assert log4shell is not None
        assert log4shell.score == pytest.approx(0.94398)
        assert reader.in_kev("CVE-2021-44228") is True
        assert reader.in_kev("CVE-2024-3094") is False  # low EPSS, not in KEV
        assert reader.epss("CVE-0000-0000") is None

        stamp = reader.version_stamp()
        assert stamp.epss_score_date == "2026-08-03"
        assert stamp.kev_catalog_version == "2026.08.01"

    def test_batch_reads(self):
        _run_refresh(_epss(date(2026, 8, 3)), _kev("2026.08.01", ("CVE-2021-44228",)))
        reader = VulnIntelReader()
        scores = reader.epss_scores(["CVE-2021-44228", "CVE-2024-3094", "CVE-9999-1"])
        assert set(scores) == {"CVE-2021-44228", "CVE-2024-3094"}
        assert reader.kev_members(["CVE-2021-44228", "CVE-2024-3094"]) == {"CVE-2021-44228"}

    def test_publishes_vuln_intel_refreshed(self):
        from components.shared_kernel.domain.events import VulnIntelRefreshed

        publisher = _CapturingPublisher()
        _run_refresh(_epss(date(2026, 8, 3)), _kev("2026.08.01", ("CVE-2021-44228",)), publisher)
        assert len(publisher.events) == 1
        evt = publisher.events[0]
        assert isinstance(evt, VulnIntelRefreshed)
        assert evt.epss_score_date == "2026-08-03"
        assert evt.kev_catalog_version == "2026.08.01"

    def test_resnapshot_is_idempotent_and_latest_wins(self):
        # Day 1: CVE-2024-3094 NOT in KEV.
        _run_refresh(_epss(date(2026, 8, 3)), _kev("2026.08.01", ("CVE-2021-44228",)))
        assert VulnIntelReader().in_kev("CVE-2024-3094") is False

        # Day 2: a newer KEV catalog now lists CVE-2024-3094 — the latest snapshot wins.
        _run_refresh(_epss(date(2026, 8, 4)), _kev("2026.08.02", ("CVE-2021-44228", "CVE-2024-3094")))
        reader = VulnIntelReader()
        assert reader.in_kev("CVE-2024-3094") is True
        assert reader.version_stamp().epss_score_date == "2026-08-04"

        # Re-pull the SAME day-2 versions → idempotent (no duplicate rows).
        from infrastructure.persistence.vuln_intel.models import EpssScore, EpssSnapshot, KevEntry

        _run_refresh(_epss(date(2026, 8, 4)), _kev("2026.08.02", ("CVE-2021-44228", "CVE-2024-3094")))
        assert EpssSnapshot.objects.filter(score_date=date(2026, 8, 4)).count() == 1
        latest = EpssSnapshot.objects.get(score_date=date(2026, 8, 4))
        assert EpssScore.objects.filter(snapshot=latest).count() == 2
        assert KevEntry.objects.count() == 3  # 1 (v1) + 2 (v2, replaced-in-place on re-pull)

    def test_retention_prunes_old_snapshots(self):
        from datetime import timedelta

        from infrastructure.persistence.vuln_intel.models import EpssSnapshot

        # Land 9 daily EPSS snapshots (KEV static) via successive refreshes.
        base = date(2026, 8, 1)
        for i in range(9):
            _run_refresh(_epss(base + timedelta(days=i)), _kev("2026.08.01", ("CVE-2021-44228",)))

        # W4: only the most-recent 7 are retained; the 2 oldest are pruned.
        remaining = set(EpssSnapshot.objects.values_list("score_date", flat=True))
        assert len(remaining) == 7
        assert base not in remaining  # 2026-08-01 pruned
        assert (base + timedelta(days=8)) in remaining  # newest kept
        # The reader still resolves the latest snapshot.
        assert VulnIntelReader().version_stamp().epss_score_date == "2026-08-09"

    def test_one_feed_failure_does_not_sink_the_other(self):
        class _BoomEpss(EpssFeedPort):
            def fetch(self):
                raise RuntimeError("epss down")

        result = RefreshFeedsUseCase(
            epss_feed=_BoomEpss(),
            kev_feed=_FakeKevFeed(_kev("2026.08.01", ("CVE-2021-44228",))),
            store=VulnSnapshotRepository(),
        ).execute()
        assert result.kev_catalog_version == "2026.08.01"
        assert result.epss_score_date is None
        assert any("epss" in e for e in result.errors)
