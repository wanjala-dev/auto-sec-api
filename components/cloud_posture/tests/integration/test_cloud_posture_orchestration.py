"""Autonomy + on-demand orchestration for the Prowler CSPM loop — spine edition (audit R1).

Covers the behaviours the migration must preserve AND the provenance it adds:
- a single-account connection links its management account (else the scheduler
  silently scans nothing);
- the scheduler / fan-out scans every non-terminal account link, through the
  anti-spam gate;
- the scan attempt IS the per-account verification (success -> VERIFIED via the
  post-ingest hook, failure -> FAILED via the failure hook);
- a run records an honest ``ScanRun`` row: trigger, triggered_by, engine
  version, real timestamps — and a FAILED row + error when the engine fails
  (previously a failed CSPM scan left NO record at all);
- the dispatch lock is RELEASED on failure (no stuck cooldown);
- scan lifecycle transitions land in the immutable audit trail (audit R4);
- the on-demand "Scan now" endpoint stamps ``request.user`` as triggered_by,
  returns 202, and honestly 429s when every account is gated.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from components.cloud_posture.infrastructure.services.scan_dispatch_service import (
    dispatch_account_scan,
    dispatch_connection_scans,
)
from components.cloud_posture.infrastructure.tasks.cloud_posture_tasks import (
    schedule_prowler_runs,
)
from components.cloud_posture.tests._prowler_backend_stub import RecordsBackend
from components.integrations.infrastructure.adapters.sts_org_adapter import StsOrgAdapter
from components.scanning.infrastructure.tasks.scan_tasks import run_scan
from infrastructure.persistence.audit.models import EntityAuditLog
from infrastructure.persistence.core.models import FeatureFlag
from infrastructure.persistence.integrations.models import AwsAccountLink, AwsOrganizationConnection
from infrastructure.persistence.scanning.models import ScanRun
from infrastructure.persistence.workspaces.models import WorkspaceMembership

_SOURCE = "cloud_posture.prowler"
_DISPATCH = "components.scanning.application.providers.scan_dispatch_provider.dispatch_scan"
# ProwlerScanner runs the engine on a ScanExecutionBackend (ADR 0006); patch the backend
# provider so the real scanner executes against canned records without a Prowler install.
_BACKEND_PROVIDER = "components.scanning.application.providers.execution_backend_provider.build_execution_backend"
# The generic scan task's default AWS assume-role vend (the single token-vending seam).
_CREDS_PROVIDER = "components.integrations.application.providers.aws_credentials_provider.get_aws_credentials_port"
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
        _CREDS_PROVIDER,
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
    def test_dispatch_skips_terminal_links_only(self, workspace_factory):
        conn = _conn(workspace_factory())
        _link(conn, "1", AwsAccountLink.Status.DISCOVERED)
        _link(conn, "2", AwsAccountLink.Status.VERIFIED)
        _link(conn, "3", AwsAccountLink.Status.FAILED)
        _link(conn, "4", AwsAccountLink.Status.SUSPENDED)
        _link(conn, "5", AwsAccountLink.Status.EXCLUDED)

        with patch(_DISPATCH) as m_dispatch:
            counts = dispatch_connection_scans(conn, trigger="schedule")

        assert counts["enqueued"] == 2  # discovered + verified; the three terminal ones skipped
        assert m_dispatch.call_count == 2

    def test_dispatch_carries_provenance_and_regions(self, workspace_factory, user_factory):
        conn = _conn(workspace_factory())
        conn.regions = ["us-east-1", "eu-west-1"]
        conn.save(update_fields=["regions"])
        _link(conn, "863183417583", AwsAccountLink.Status.VERIFIED)
        operator = user_factory()

        with patch(_DISPATCH) as m_dispatch:
            dispatch_connection_scans(conn, trigger="manual", triggered_by=operator.id)

        kwargs = m_dispatch.call_args.kwargs
        assert kwargs["source"] == _SOURCE
        assert kwargs["target_ref"] == "863183417583"
        assert kwargs["trigger"] == "manual"
        assert kwargs["triggered_by"] == str(operator.id)
        assert kwargs["params"] == {"regions": ["us-east-1", "eu-west-1"]}

    def test_second_dispatch_is_gated_while_first_is_in_flight(self, workspace_factory):
        conn = _conn(workspace_factory())

        with patch(_DISPATCH):
            first = dispatch_account_scan(conn, "863183417583", trigger="manual")
            second = dispatch_account_scan(conn, "863183417583", trigger="manual")

        assert first["enqueued"] is True
        assert second["enqueued"] is False
        assert second["reason"] == "running"

    @pytest.mark.real_feature_flags
    def test_the_seam_refuses_a_workspace_that_disabled_cloud_posture(self, workspace_factory):
        """The capability gate lives on the dispatch seam, not on its callers.

        Every trigger — Scan now, the beat sweep, the post-verify auto-scan and
        the deprecated per-account shim — funnels through these two functions.
        Enforcing here is what makes ``feature.cloud_posture`` an actual
        kill-switch instead of a convention three call sites have to remember.
        """
        from components.shared_platform.infrastructure.services.feature_flags import set_workspace_flag

        ws = workspace_factory()
        FeatureFlag.objects.update_or_create(key="feature.cloud_posture", defaults={"default_enabled": True})
        set_workspace_flag("feature.cloud_posture", ws.id, False)
        conn = _conn(ws, connected=True)
        _link(conn, "863183417583", AwsAccountLink.Status.VERIFIED)

        with patch(_DISPATCH) as m_dispatch:
            counts = dispatch_connection_scans(conn, trigger="schedule")
            # The per-account primitive is the shim's entry point — gate it too,
            # or a stale broker message walks straight past the switch.
            verdict = dispatch_account_scan(conn, "863183417583", trigger="schedule")

        assert m_dispatch.call_count == 0
        assert counts["scannable"] == 0
        assert counts["skipped_reason"] == "cloud_posture_not_enabled"
        assert verdict["enqueued"] is False
        assert verdict["reason"] == "cloud_posture_not_enabled"

    def test_scheduler_fans_out_discovered_links(self, workspace_factory):
        conn = _conn(workspace_factory(), connected=True)
        _link(conn, "863183417583", AwsAccountLink.Status.DISCOVERED)
        flags = MagicMock()
        flags.is_feature_enabled.return_value = True

        with (
            patch(_DISPATCH) as m_dispatch,
            patch(
                "components.shared_platform.application.providers.feature_flags_provider.get_feature_flags_provider",
                return_value=flags,
            ),
        ):
            result = schedule_prowler_runs()

        assert result["scheduled"] == 1
        m_dispatch.assert_called_once()
        assert m_dispatch.call_args.kwargs["trigger"] == "schedule"


def _run_spine_scan(conn, *, backend, creds_port, triggered_by=None):
    with (
        patch(_CREDS_PROVIDER, return_value=creds_port),
        patch(_BACKEND_PROVIDER, return_value=backend),
    ):
        return run_scan(
            source=_SOURCE,
            workspace_id=str(conn.workspace_id),
            target_ref="863183417583",
            connection_id=str(conn.id),
            account_id="863183417583",
            trigger="manual",
            triggered_by=str(triggered_by) if triggered_by else None,
        )


@pytest.mark.integration
@pytest.mark.django_db
class TestSpineScanEndToEnd:
    """The REAL generic run_scan task drives the REAL ProwlerScanner (stub backend)."""

    def test_success_records_run_promotes_link_and_audits(self, workspace_factory, user_factory):
        ws = workspace_factory()
        conn = _conn(ws)
        link = _link(conn, "863183417583", AwsAccountLink.Status.DISCOVERED)
        operator = user_factory()
        port = MagicMock()
        port.assume_role.return_value = _CREDS

        result = _run_spine_scan(conn, backend=RecordsBackend(_RECORDS), creds_port=port, triggered_by=operator.id)

        assert result["success"] is True
        # The run row IS the provenance envelope: trigger, operator, engine, timings.
        run = ScanRun.objects.get(workspace=ws, source=_SOURCE, target_ref="863183417583")
        assert run.status == ScanRun.Status.COMPLETED
        assert run.trigger == "manual"
        assert str(run.triggered_by_id) == str(operator.id)
        assert run.engine == "prowler"
        assert run.started_at is not None and run.completed_at is not None
        assert run.total_checks == 1
        # The scan proved the role — the link is VERIFIED (post-ingest hook).
        link.refresh_from_db()
        assert link.status == AwsAccountLink.Status.VERIFIED
        # Audit trail (R4): triggered + completed transitions on the run entity.
        transitions = set(
            EntityAuditLog.objects.filter(workspace=ws, object_id=str(run.id)).values_list("new_value", flat=True)
        )
        assert {"running", "completed"} <= transitions

    def test_failure_records_failed_run_marks_link_and_releases_lock(self, workspace_factory):
        from django.core.cache import cache

        from components.scanning.infrastructure.services.scan_gate import dispatch_lock_key

        ws = workspace_factory()
        conn = _conn(ws)
        link = _link(conn, "863183417583", AwsAccountLink.Status.VERIFIED)
        port = MagicMock()
        port.assume_role.return_value = _CREDS
        # Simulate the gate having locked this dispatch (the real trigger path does).
        cache.add(dispatch_lock_key(str(ws.id), _SOURCE, "863183417583"), "x", 3600)

        result = _run_spine_scan(conn, backend=RecordsBackend([], exit_code=1), creds_port=port)

        assert result["success"] is False
        # A failed scan leaves an HONEST record (previously: no row at all).
        run = ScanRun.objects.get(workspace=ws, source=_SOURCE, target_ref="863183417583")
        assert run.status == ScanRun.Status.FAILED
        assert run.error
        assert run.completed_at is not None
        # The failure hook degrades the one account.
        link.refresh_from_db()
        assert link.status == AwsAccountLink.Status.FAILED
        # The dispatch lock is released — a transient failure must not cooldown-lock.
        assert cache.get(dispatch_lock_key(str(ws.id), _SOURCE, "863183417583")) is None
        # Audit trail (R4): the failed transition is recorded.
        failed = EntityAuditLog.objects.filter(workspace=ws, object_id=str(run.id), new_value="failed")
        assert failed.exists()


@pytest.mark.integration
@pytest.mark.django_db
class TestScanNowEndpoint:
    def _url(self, ws, conn):
        return f"/integrations/workspaces/{ws.id}/aws/{conn.id}/scan/"

    def _setup(self, workspace_factory, user_factory):
        call_command("seed_workspace_roles")
        ws = workspace_factory()
        conn = _conn(ws, connected=True)
        _link(conn, "863183417583", AwsAccountLink.Status.DISCOVERED)
        FeatureFlag.objects.get_or_create(key="feature.cloud_posture", defaults={"default_enabled": True})
        owner = user_factory()
        WorkspaceMembership.objects.create(workspace=ws, user=owner, role="owner", status="active")
        return ws, conn, owner

    def test_enqueues_async_with_operator_provenance_and_returns_202(self, api_client, workspace_factory, user_factory):
        ws, conn, owner = self._setup(workspace_factory, user_factory)
        api_client.force_authenticate(owner)

        with patch(_DISPATCH) as m_dispatch:
            resp = api_client.post(self._url(ws, conn))

        assert resp.status_code == 202, resp.data
        assert resp.data["data"]["enqueued"] == 1
        m_dispatch.assert_called_once()
        # request.user is no longer dropped on the floor — it rides to the run row.
        assert m_dispatch.call_args.kwargs["triggered_by"] == str(owner.id)
        assert m_dispatch.call_args.kwargs["trigger"] == "manual"

    def test_second_scan_now_is_gated_with_429(self, api_client, workspace_factory, user_factory):
        ws, conn, owner = self._setup(workspace_factory, user_factory)
        api_client.force_authenticate(owner)

        with patch(_DISPATCH):
            first = api_client.post(self._url(ws, conn))
            second = api_client.post(self._url(ws, conn))

        assert first.status_code == 202
        assert second.status_code == 429, second.data
        assert second.data["error"] == "scan_gated"
        assert second.data["blocked"] == 1

    def test_non_member_forbidden(self, api_client, workspace_factory, user_factory):
        call_command("seed_workspace_roles")
        ws = workspace_factory()
        conn = _conn(ws)
        api_client.force_authenticate(user_factory())
        resp = api_client.post(self._url(ws, conn))
        assert resp.status_code == 403


@pytest.mark.integration
@pytest.mark.django_db
class TestScanReportsBackgroundJob:
    """The scan surfaces as the generic security_scan BackgroundJob (HUD progress)."""

    def test_success_reports_completed_job(self, workspace_factory):
        from infrastructure.persistence.core.models import BackgroundJob

        conn = _conn(workspace_factory())
        _link(conn, "863183417583", AwsAccountLink.Status.DISCOVERED)
        port = MagicMock()
        port.assume_role.return_value = _CREDS

        _run_spine_scan(conn, backend=RecordsBackend(_RECORDS), creds_port=port)

        job = BackgroundJob.objects.filter(job_type="security_scan").latest("created_at")
        assert job.status == BackgroundJob.Status.COMPLETED
        assert job.progress == 100

    def test_failure_reports_failed_job(self, workspace_factory):
        from infrastructure.persistence.core.models import BackgroundJob

        conn = _conn(workspace_factory())
        _link(conn, "863183417583", AwsAccountLink.Status.DISCOVERED)
        port = MagicMock()
        port.assume_role.return_value = _CREDS

        _run_spine_scan(conn, backend=RecordsBackend([], exit_code=1), creds_port=port)

        job = BackgroundJob.objects.filter(job_type="security_scan").latest("created_at")
        assert job.status == BackgroundJob.Status.FAILED
