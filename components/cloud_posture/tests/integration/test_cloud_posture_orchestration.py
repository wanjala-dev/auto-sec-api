"""Autonomy + on-demand orchestration for the Prowler CSPM loop.

Covers the fixes that make the loop actually run end-to-end:
- a single-account connection links its management account (else the scheduler
  silently scans nothing);
- the scheduler / fan-out scans every non-terminal account link;
- the scan attempt IS the per-account verification (success -> VERIFIED,
  failure -> FAILED);
- the on-demand "Scan now" endpoint enqueues async work and returns 202
  (never runs Prowler in the request path).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from components.cloud_posture.infrastructure.tasks.cloud_posture_tasks import (
    enqueue_connection_scans,
    run_prowler_scan_for_account,
    schedule_prowler_runs,
)
from components.integrations.infrastructure.adapters.sts_org_adapter import StsOrgAdapter
from infrastructure.persistence.core.models import FeatureFlag
from infrastructure.persistence.integrations.models import AwsAccountLink, AwsOrganizationConnection
from infrastructure.persistence.workspaces.models import WorkspaceMembership

_TASK = "components.cloud_posture.infrastructure.tasks.cloud_posture_tasks"
_CREDS = {"AccessKeyId": "AK", "SecretAccessKey": "s", "SessionToken": "t"}
_RECORDS = [
    {
        "metadata": {"event_code": "x"},
        "status_code": "PASS",
        "severity": "Low",
        "finding_info": {"uid": "u", "title": "t"},
        "resources": [{"uid": "r"}],
        "cloud": {"account": {"uid": "863183417583"}},
    }
]


def _conn(ws, *, connected=False):
    conn = AwsOrganizationConnection.objects.create(
        workspace=ws,
        management_account_id="863183417583",
        external_id=f"ext-{uuid.uuid4().hex[:10]}",
        role_name="AutoSecAuditRole",
    )
    if connected:
        conn.status = AwsOrganizationConnection.Status.CONNECTED
        conn.save(update_fields=["status"])
    return conn


def _link(conn, account_id, status):
    return AwsAccountLink.objects.create(connection=conn, account_id=account_id, status=status)


@pytest.mark.unit
def test_verify_links_management_account_for_single_account():
    """discover=False (single-account) still yields the management account."""
    port = MagicMock()
    port.assume_role.return_value = _CREDS
    with patch(
        "components.integrations.application.providers.aws_credentials_provider.get_aws_credentials_port",
        return_value=port,
    ):
        result = StsOrgAdapter().verify_and_discover(
            management_account_id="863183417583",
            role_name="AutoSecAuditRole",
            external_id="ext",
            discover=False,
        )
    assert result["accounts"] == [{"id": "863183417583", "name": ""}]


@pytest.mark.integration
@pytest.mark.django_db
class TestFanOut:
    def test_enqueue_skips_terminal_links_only(self, workspace_factory):
        conn = _conn(workspace_factory())
        _link(conn, "1", AwsAccountLink.Status.DISCOVERED)
        _link(conn, "2", AwsAccountLink.Status.VERIFIED)
        _link(conn, "3", AwsAccountLink.Status.FAILED)
        _link(conn, "4", AwsAccountLink.Status.SUSPENDED)
        _link(conn, "5", AwsAccountLink.Status.EXCLUDED)

        with patch(f"{_TASK}.run_prowler_scan_for_account.delay") as m_delay:
            enqueued = enqueue_connection_scans(conn)

        assert enqueued == 2  # discovered + verified; the three terminal ones skipped
        assert m_delay.call_count == 2

    def test_scheduler_fans_out_discovered_links(self, workspace_factory):
        conn = _conn(workspace_factory(), connected=True)
        _link(conn, "863183417583", AwsAccountLink.Status.DISCOVERED)
        flags = MagicMock()
        flags.is_feature_enabled.return_value = True

        with (
            patch(f"{_TASK}.run_prowler_scan_for_account.delay") as m_delay,
            patch(
                "components.shared_platform.application.providers.feature_flags_provider.get_feature_flags_provider",
                return_value=flags,
            ),
        ):
            result = schedule_prowler_runs()

        assert result["scheduled"] == 1
        m_delay.assert_called_once()


@pytest.mark.integration
@pytest.mark.django_db
class TestScanVerifiesLink:
    def test_success_promotes_link_to_verified(self, workspace_factory):
        conn = _conn(workspace_factory())
        link = _link(conn, "863183417583", AwsAccountLink.Status.DISCOVERED)
        port = MagicMock()
        port.assume_role.return_value = _CREDS

        with (
            patch(f"{_TASK}.get_aws_credentials_port", return_value=port),
            patch(f"{_TASK}.run_prowler", return_value=_RECORDS),
        ):
            result = run_prowler_scan_for_account(str(conn.id), "863183417583")

        assert result["success"] is True
        link.refresh_from_db()
        assert link.status == AwsAccountLink.Status.VERIFIED

    def test_failure_marks_link_failed(self, workspace_factory):
        conn = _conn(workspace_factory())
        link = _link(conn, "863183417583", AwsAccountLink.Status.DISCOVERED)
        port = MagicMock()
        port.assume_role.side_effect = RuntimeError("assume denied")

        with patch(f"{_TASK}.get_aws_credentials_port", return_value=port):
            result = run_prowler_scan_for_account(str(conn.id), "863183417583")

        assert result["success"] is False
        link.refresh_from_db()
        assert link.status == AwsAccountLink.Status.FAILED


@pytest.mark.integration
@pytest.mark.django_db
class TestScanNowEndpoint:
    def _url(self, ws, conn):
        return f"/integrations/workspaces/{ws.id}/aws/{conn.id}/scan/"

    def test_enqueues_async_and_returns_202(self, api_client, workspace_factory, user_factory):
        call_command("seed_workspace_roles")
        ws = workspace_factory()
        conn = _conn(ws, connected=True)
        _link(conn, "863183417583", AwsAccountLink.Status.DISCOVERED)
        FeatureFlag.objects.get_or_create(key="feature.cloud_posture", defaults={"default_enabled": True})
        owner = user_factory()
        WorkspaceMembership.objects.create(workspace=ws, user=owner, role="owner", status="active")
        api_client.force_authenticate(owner)

        with patch(f"{_TASK}.run_prowler_scan_for_account.delay") as m_delay:
            resp = api_client.post(self._url(ws, conn))

        assert resp.status_code == 202, resp.data
        assert resp.data["data"]["enqueued"] == 1
        m_delay.assert_called_once()

    def test_non_member_forbidden(self, api_client, workspace_factory, user_factory):
        call_command("seed_workspace_roles")
        ws = workspace_factory()
        conn = _conn(ws)
        api_client.force_authenticate(user_factory())
        resp = api_client.post(self._url(ws, conn))
        assert resp.status_code == 403
