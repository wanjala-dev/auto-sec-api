"""Integration: the background recompute materializes FindingRisk from findings + intel + exposure.

Exercises the full wired use case (`FindingProvider.build_recompute_finding_risk_use_case`)
against real repos, a real EPSS/KEV snapshot, and a real CloudAsset exposure — proving the
ADR 0013 blend end to end, including the "KEV entry flips a score without a finding change"
feed-refresh trigger and the CQRS ranked read.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.utils import timezone

from components.findings.application.providers.finding_provider import FindingProvider
from components.findings.application.queries.list_findings_query import ListFindingsQuery
from components.vuln_intel.domain.value_objects.feed_snapshot import (
    EpssFeedSnapshot,
    EpssRecord,
    KevFeedSnapshot,
    KevRecord,
)
from components.vuln_intel.infrastructure.repositories.vuln_snapshot_repository import VulnSnapshotRepository
from infrastructure.persistence.cloud_graph.models import CloudAsset
from infrastructure.persistence.findings.models import Finding, FindingRisk

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_LOG4SHELL = "CVE-2021-44228"
_PUBLIC_URN = "arn:aws:ec2:us-east-1:111122223333:instance/i-public"
_PRIVATE_URN = "arn:aws:ec2:us-east-1:111122223333:instance/i-private"


def _asset(ws, urn, exposure):
    now = timezone.now()
    return CloudAsset.objects.create(
        workspace=ws,
        arn=urn,
        asset_urn=urn,
        resource_type="aws_ec2_instance",
        exposure=exposure,
        first_seen_at=now,
        last_seen_at=now,
    )


def _finding(ws, *, fingerprint, urn, severity="critical", cve=_LOG4SHELL, cvss=9.8):
    now = timezone.now()
    attrs = {}
    if cve:
        attrs["vulnerability_id"] = cve
    if cvss is not None:
        attrs["cvss_base"] = cvss
    return Finding.objects.create(
        workspace=ws,
        source="container_security.trivy",
        fingerprint=fingerprint,
        asset_urn=urn,
        severity=severity,
        status="open",
        title=f"{cve or 'misconfig'} on {urn}",
        attributes=attrs,
        first_seen_at=now,
        last_seen_at=now,
    )


def _seed_epss(records):
    VulnSnapshotRepository().save_epss_snapshot(
        EpssFeedSnapshot(
            score_date=date(2026, 8, 3),
            model_version="v1",
            records=tuple(EpssRecord(cve=c, epss=e, percentile=p) for c, e, p in records),
        )
    )


def _seed_kev(version, cves):
    VulnSnapshotRepository().save_kev_snapshot(
        KevFeedSnapshot(catalog_version=version, records=tuple(KevRecord(cve=c) for c in cves))
    )


def _recompute(ws):
    return FindingProvider.build_recompute_finding_risk_use_case().execute(ws.id, timezone.now())


class TestRecompute:
    def test_materializes_scores_with_intel_and_exposure(self, workspace_factory):
        ws = workspace_factory()
        _asset(ws, _PUBLIC_URN, "public")
        _asset(ws, _PRIVATE_URN, "private")
        _seed_epss([(_LOG4SHELL, 0.94, 0.99)])
        _seed_kev("2026.08.01", [_LOG4SHELL])
        f_public = _finding(ws, fingerprint="fp-public", urn=_PUBLIC_URN)
        f_private = _finding(ws, fingerprint="fp-private", urn=_PRIVATE_URN)

        scored = _recompute(ws)
        assert scored == 2

        risk_public = FindingRisk.objects.get(finding=f_public)
        risk_private = FindingRisk.objects.get(finding=f_private)
        assert risk_public.in_kev is True
        assert risk_public.band == "red"
        assert risk_public.epss == pytest.approx(0.94)
        assert risk_public.exposure == "public"
        # KEV floors both to RED, but the public one still outranks the private one.
        assert risk_public.score >= risk_private.score

    def test_exposure_unknown_flagged_when_no_asset(self, workspace_factory):
        ws = workspace_factory()
        _seed_epss([(_LOG4SHELL, 0.5, 0.8)])
        _seed_kev("2026.08.01", [])
        f = _finding(ws, fingerprint="fp-x", urn="urn:unknown:asset")

        _recompute(ws)
        risk = FindingRisk.objects.get(finding=f)
        assert risk.exposure_unknown is True
        assert risk.exposure == "private"

    def test_kev_entry_flips_score_without_a_finding_change(self, workspace_factory):
        ws = workspace_factory()
        _asset(ws, _PUBLIC_URN, "public")
        _seed_epss([(_LOG4SHELL, 0.02, 0.3)])  # low EPSS
        _seed_kev("2026.08.01", [])  # NOT yet in KEV
        f = _finding(ws, fingerprint="fp-flip", urn=_PUBLIC_URN, severity="medium", cvss=5.0)

        _recompute(ws)
        before = FindingRisk.objects.get(finding=f)
        assert before.in_kev is False
        assert before.band != "red"

        # The daily feed moved: a newer KEV catalog now lists the CVE. No finding changed.
        _seed_kev("2026.08.02", [_LOG4SHELL])
        _recompute(ws)
        after = FindingRisk.objects.get(finding=f)
        assert after.in_kev is True
        assert after.band == "red"  # KEV floors to RED on the feed move alone

    def test_recompute_is_idempotent(self, workspace_factory):
        ws = workspace_factory()
        _asset(ws, _PUBLIC_URN, "public")
        _seed_epss([(_LOG4SHELL, 0.5, 0.8)])
        _seed_kev("2026.08.01", [_LOG4SHELL])
        f = _finding(ws, fingerprint="fp-idem", urn=_PUBLIC_URN)

        _recompute(ws)
        _recompute(ws)
        assert FindingRisk.objects.filter(finding=f).count() == 1

    def test_single_finding_rescore(self, workspace_factory):
        ws = workspace_factory()
        _seed_epss([(_LOG4SHELL, 0.5, 0.8)])
        _seed_kev("2026.08.01", [])
        a = _finding(ws, fingerprint="fp-a", urn="urn:a")
        b = _finding(ws, fingerprint="fp-b", urn="urn:b")

        FindingProvider.build_recompute_finding_risk_use_case().execute(ws.id, timezone.now(), finding_id=a.id)
        assert FindingRisk.objects.filter(finding=a).count() == 1
        assert FindingRisk.objects.filter(finding=b).count() == 0


class TestRankedRead:
    def test_list_orders_by_contextual_risk(self, workspace_factory):
        ws = workspace_factory()
        _asset(ws, _PUBLIC_URN, "public")
        _asset(ws, _PRIVATE_URN, "private")
        _seed_epss([(_LOG4SHELL, 0.94, 0.99)])
        _seed_kev("2026.08.01", [])
        # Same CVE, one public (higher score) one private (lower).
        _finding(ws, fingerprint="fp-hi", urn=_PUBLIC_URN)
        _finding(ws, fingerprint="fp-lo", urn=_PRIVATE_URN)
        _recompute(ws)

        page = FindingProvider.build_list_findings_use_case().execute(
            ListFindingsQuery(workspace_id=ws.id, order_by="contextual_risk")
        )
        assert len(page.items) == 2
        scores = [row.risk.score for row in page.items]
        assert scores == sorted(scores, reverse=True)  # highest first
        assert page.items[0].finding.asset_urn == _PUBLIC_URN
        assert page.items[0].risk is not None
        assert page.items[0].risk.in_kev is False
