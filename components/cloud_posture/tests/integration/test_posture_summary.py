"""Tests for the CLOUD POSTURE summary read API (powers the HUD card)."""

from __future__ import annotations

import pytest

from infrastructure.persistence.cloud_posture.models import CloudPostureFinding, CloudPostureScan
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _url(ws):
    return f"/api/v1/cloud-posture/workspaces/{ws.id}/summary/"


def test_summary_aggregates_findings_by_severity(api_client, workspace_factory, user_factory):
    ws = workspace_factory()
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    scan = CloudPostureScan.objects.create(
        workspace=ws, account_id="863183417583", status="completed", total_checks=10, failed_count=2
    )
    CloudPostureFinding.objects.create(
        workspace=ws, scan=scan, check_id="c1", severity="high", account_id="863183417583", resource_uid="r1"
    )
    CloudPostureFinding.objects.create(
        workspace=ws, scan=scan, check_id="c2", severity="critical", account_id="863183417583", resource_uid="r2"
    )

    api_client.force_authenticate(member)
    resp = api_client.get(_url(ws))

    assert resp.status_code == 200, resp.data
    data = resp.data["data"]
    assert data["account_count"] == 1
    assert data["totals"]["findings_by_severity"]["high"] == 1
    assert data["totals"]["findings_by_severity"]["critical"] == 1
    acct = data["accounts"][0]
    assert acct["account_id"] == "863183417583"
    assert acct["scan"]["failed_count"] == 2
    assert acct["findings_by_severity"]["high"] == 1


def test_non_member_forbidden(api_client, workspace_factory, user_factory):
    ws = workspace_factory()
    api_client.force_authenticate(user_factory())
    resp = api_client.get(_url(ws))
    assert resp.status_code == 403
