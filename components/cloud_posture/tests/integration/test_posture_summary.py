"""Tests for the CLOUD POSTURE summary read API (powers the HUD card).

Spine-native (audit R2): the summary aggregates the latest completed
``ScanRun`` per account + OPEN Finding-SSOT severity counts — the legacy
``CloudPostureScan``/``CloudPostureFinding`` tables are gone.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from infrastructure.persistence.findings.models import Finding
from infrastructure.persistence.scanning.models import ScanRun
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_SOURCE = "cloud_posture.prowler"
_ACCOUNT = "863183417583"


def _url(ws):
    return f"/api/v1/cloud-posture/workspaces/{ws.id}/summary/"


def _run(ws, **overrides):
    defaults = dict(
        workspace=ws,
        source=_SOURCE,
        target_ref=_ACCOUNT,
        account_id=_ACCOUNT,
        status=ScanRun.Status.COMPLETED,
        engine="prowler",
        total_checks=10,
        passed_count=8,
        failed_count=2,
        started_at=timezone.now(),
        completed_at=timezone.now(),
    )
    defaults.update(overrides)
    return ScanRun.objects.create(**defaults)


def _finding(ws, *, check_id: str, severity: str, account: str = _ACCOUNT, status: str = "open", **attrs):
    now = timezone.now()
    return Finding.objects.create(
        workspace=ws,
        source=_SOURCE,
        fingerprint=f"{check_id}|{account}|r-{check_id}",
        asset_urn=f"arn:aws:x:::{check_id}",
        severity=severity,
        status=status,
        title=attrs.pop("title", check_id),
        attributes={"check_id": check_id, "account_id": account, **attrs},
        first_seen_at=now,
        last_seen_at=now,
    )


def test_summary_aggregates_open_findings_by_severity(api_client, workspace_factory, user_factory):
    ws = workspace_factory()
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    _run(ws)
    _finding(ws, check_id="c1", severity="high")
    _finding(ws, check_id="c2", severity="critical")
    # Resolved findings do NOT count — the card shows the open surface.
    _finding(ws, check_id="c3", severity="high", status="resolved")

    api_client.force_authenticate(member)
    resp = api_client.get(_url(ws))

    assert resp.status_code == 200, resp.data
    data = resp.data["data"]
    assert data["account_count"] == 1
    assert data["totals"]["findings_by_severity"]["high"] == 1
    assert data["totals"]["findings_by_severity"]["critical"] == 1
    acct = data["accounts"][0]
    assert acct["account_id"] == _ACCOUNT
    assert acct["scan"]["failed_count"] == 2
    assert acct["scan"]["total_checks"] == 10
    assert acct["findings_by_severity"]["high"] == 1


def test_summary_uses_latest_completed_run_and_skips_failed(api_client, workspace_factory, user_factory):
    ws = workspace_factory()
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    _run(ws, failed_count=9)
    latest = _run(ws, failed_count=1)
    # A newer FAILED run must not shadow the completed history the card renders.
    _run(ws, status=ScanRun.Status.FAILED, failed_count=0, error="engine crashed")

    api_client.force_authenticate(member)
    resp = api_client.get(_url(ws))

    acct = resp.data["data"]["accounts"][0]
    assert acct["scan"]["id"] == str(latest.id)
    assert acct["scan"]["failed_count"] == 1


def test_non_member_forbidden(api_client, workspace_factory, user_factory):
    ws = workspace_factory()
    api_client.force_authenticate(user_factory())
    resp = api_client.get(_url(ws))
    assert resp.status_code == 403


def test_findings_drilldown_filters_by_severity(api_client, workspace_factory, user_factory):
    ws = workspace_factory()
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    _run(ws, total_checks=5)
    _finding(ws, check_id="c1", severity="high", title="Public bucket", service="s3")
    _finding(ws, check_id="c2", severity="critical", title="Root access key", service="iam")

    api_client.force_authenticate(member)
    resp = api_client.get(f"/api/v1/cloud-posture/workspaces/{ws.id}/findings/?severity=high")

    assert resp.status_code == 200, resp.data
    data = resp.data["data"]
    assert len(data) == 1
    assert data[0]["title"] == "Public bucket"
    assert data[0]["service"] == "s3"


def test_findings_drilldown_excludes_other_sources(api_client, workspace_factory, user_factory):
    """The AWS posture drill must not leak Trivy/Opengrep/Vercel findings."""
    ws = workspace_factory()
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    _finding(ws, check_id="c1", severity="high")
    now = timezone.now()
    Finding.objects.create(
        workspace=ws,
        source="container_security.trivy",
        fingerprint="cve|img|pkg",
        asset_urn="urn:image/repo:tag",
        severity="high",
        title="CVE-2026-1 in openssl",
        first_seen_at=now,
        last_seen_at=now,
    )

    api_client.force_authenticate(member)
    resp = api_client.get(f"/api/v1/cloud-posture/workspaces/{ws.id}/findings/")

    titles = [f["title"] for f in resp.data["data"]]
    assert titles == ["c1"]
