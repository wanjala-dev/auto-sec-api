"""End-to-end API test for the AWS integration loop — the second flow Tom's org hits.

Drives the REAL controller chain, stubbing only the two live cloud seams:

    POST   …/aws/                      create → 201, external_id generated server-side
    GET    …/aws/<id>/cloudformation/  the launch template, bound to this connection
    POST   …/aws/<id>/verify/          OrgVerificationPort stubbed → CONNECTED + AwsAccountLink rows
    POST   …/aws/<id>/scan/            eager Celery → RecordsBackend → a Finding in the SSOT

Plus the permission wall: 409 when ``feature.cloud_posture`` is off, and 403 for a
member who lacks ``manage_integrations``.
"""

from __future__ import annotations

import json

import pytest
from django.core.management import call_command

from components.workspace.infrastructure.repositories.workspace_setup_query_repository import (
    OrmWorkspaceSetupQueryRepository,
)
from infrastructure.persistence.findings.models import Finding
from infrastructure.persistence.integrations.models import AwsAccountLink, AwsOrganizationConnection
from infrastructure.persistence.workspaces.models import WorkspaceMembership

_MGMT_ACCOUNT = "123456789012"


def _aws_base(ws_id) -> str:
    return f"/integrations/workspaces/{ws_id}/aws/"


@pytest.mark.integration
@pytest.mark.django_db
class TestAwsConnectionLoop:
    """The full connect → cloudformation → verify → scan chain, in order."""

    def _create(self, api_client, ws, *, org_wide=False):
        return api_client.post(
            _aws_base(ws.id),
            {"management_account_id": _MGMT_ACCOUNT, "name": "Acme Org", "org_wide": org_wide},
            format="json",
        )

    def test_create_generates_external_id_server_side(self, api_client, integrations_workspace):
        ws, owner = integrations_workspace.workspace, integrations_workspace.owner
        api_client.force_authenticate(owner)

        resp = self._create(api_client, ws)
        assert resp.status_code == 201, resp.data
        body = resp.data["data"]
        assert resp.data["created"] is True
        assert body["management_account_id"] == _MGMT_ACCOUNT
        # The confused-deputy token is vendor-generated (never customer-chosen).
        assert body["external_id"].startswith("autosec-")
        # No long-lived AWS secret is ever accepted or echoed — this is role-assumption.
        assert not any(k in body for k in ("secret", "secret_access_key", "token", "password"))

    def test_create_rejects_non_12_digit_account(self, api_client, integrations_workspace):
        ws, owner = integrations_workspace.workspace, integrations_workspace.owner
        api_client.force_authenticate(owner)
        resp = api_client.post(_aws_base(ws.id), {"management_account_id": "42"}, format="json")
        assert resp.status_code == 400, resp.data

    def test_cloudformation_template_is_bound_to_the_connection(self, api_client, integrations_workspace, monkeypatch):
        # The audit role trusts exactly one principal — the platform's own account id.
        # It is deliberately fail-loud config (never a placeholder), so set it here.
        monkeypatch.setenv("AUTOSEC_VENDOR_AWS_ACCOUNT_ID", "999999999999")
        ws, owner = integrations_workspace.workspace, integrations_workspace.owner
        api_client.force_authenticate(owner)
        created = self._create(api_client, ws).data["data"]

        resp = api_client.get(f"{_aws_base(ws.id)}{created['id']}/cloudformation/")
        assert resp.status_code == 200, resp.data
        assert resp.data["format"] == "cloudformation"
        # launch_url is part of the contract (None for org-wide copy-template flows).
        assert "launch_url" in resp.data
        template_blob = json.dumps(resp.data["data"])
        # The generated template carries THIS connection's external_id + audit role.
        assert created["external_id"] in template_blob
        assert created["role_name"] in template_blob

    def test_verify_marks_connected_and_discovers_accounts(
        self, api_client, integrations_workspace, stub_org_verification
    ):
        ws, owner = integrations_workspace.workspace, integrations_workspace.owner
        api_client.force_authenticate(owner)
        created = self._create(api_client, ws).data["data"]

        accounts = [{"id": _MGMT_ACCOUNT, "name": "Prod"}, {"id": "210987654321", "name": "Staging"}]
        with stub_org_verification(accounts=accounts, organization_id="o-acme"):
            resp = api_client.post(f"{_aws_base(ws.id)}{created['id']}/verify/")

        assert resp.status_code == 200, resp.data
        body = resp.data["data"]
        assert body["status"] == "connected"
        assert body["organization_id"] == "o-acme"
        assert body["last_verified_at"] is not None
        # Discovered accounts are persisted as AwsAccountLink rows.
        links = AwsAccountLink.objects.filter(connection_id=created["id"])
        assert links.count() == 2
        assert set(links.values_list("account_id", flat=True)) == {_MGMT_ACCOUNT, "210987654321"}

    def test_verify_failure_marks_error_and_502(self, api_client, integrations_workspace):
        from unittest import mock

        ws, owner = integrations_workspace.workspace, integrations_workspace.owner
        api_client.force_authenticate(owner)
        created = self._create(api_client, ws).data["data"]

        target = "components.integrations.infrastructure.adapters.sts_org_adapter.StsOrgAdapter.verify_and_discover"
        with mock.patch(target, side_effect=RuntimeError("assume-role AccessDenied")):
            resp = api_client.post(f"{_aws_base(ws.id)}{created['id']}/verify/")

        assert resp.status_code == 502, resp.data
        conn = AwsOrganizationConnection.objects.get(id=created["id"])
        assert conn.status == AwsOrganizationConnection.Status.ERROR
        assert "AccessDenied" in conn.last_error

    def test_scan_enqueues_and_persists_a_finding(
        self,
        api_client,
        integrations_workspace,
        stub_org_verification,
        stub_scan_execution,
        django_capture_on_commit_callbacks,
    ):
        ws, owner = integrations_workspace.workspace, integrations_workspace.owner
        api_client.force_authenticate(owner)

        # Connect + verify so the connection has a discovered, scannable account link.
        created = self._create(api_client, ws).data["data"]
        with stub_org_verification(accounts=[{"id": _MGMT_ACCOUNT, "name": "Prod"}]):
            api_client.post(f"{_aws_base(ws.id)}{created['id']}/verify/")

        # Before the first scan the setup funnel's has_first_scan is False.
        assert OrmWorkspaceSetupQueryRepository._has_first_scan(ws) is False

        # Scan now: 202 + eager Celery runs the real ProwlerScanner on canned records;
        # the FindingObserved on_commit dual-write lands a row in the Finding SSOT.
        with stub_scan_execution() as backend, django_capture_on_commit_callbacks(execute=True):
            resp = api_client.post(f"{_aws_base(ws.id)}{created['id']}/scan/")

        assert resp.status_code == 202, resp.data
        assert resp.data["data"]["enqueued"] == 1
        assert len(backend.calls) == 1

        findings = Finding.objects.filter(workspace=ws, source="cloud_posture.prowler")
        assert findings.count() == 1
        finding = findings.first()
        assert finding.title == "S3 bucket is public"
        assert finding.severity == "high"

        # The scan advanced the getting-started funnel.
        assert OrmWorkspaceSetupQueryRepository._has_first_scan(ws) is True


@pytest.mark.integration
@pytest.mark.django_db
class TestAwsScanPermissionWall:
    def _connection(self, ws) -> AwsOrganizationConnection:
        return AwsOrganizationConnection.objects.create(
            workspace=ws,
            management_account_id=_MGMT_ACCOUNT,
            external_id="autosec-fixed-e2e",
            role_name="AutoSecAuditRole",
            status=AwsOrganizationConnection.Status.CONNECTED,
        )

    @pytest.mark.real_feature_flags
    def test_scan_409_when_cloud_posture_flag_off(self, api_client, integrations_workspace):
        # Real flag cascade + no seeded feature.cloud_posture row → the gate is off.
        ws, owner = integrations_workspace.workspace, integrations_workspace.owner
        conn = self._connection(ws)
        api_client.force_authenticate(owner)

        resp = api_client.post(f"{_aws_base(ws.id)}{conn.id}/scan/")
        assert resp.status_code == 409, resp.data
        assert resp.data["error"] == "cloud_posture_not_enabled"

    def test_scan_403_for_member_without_manage_integrations(self, api_client, integrations_workspace, user_factory):
        # A viewer-role member lacks manage_integrations → the endpoint is walled off.
        call_command("seed_workspace_roles")
        ws = integrations_workspace.workspace
        conn = self._connection(ws)
        viewer = user_factory()
        WorkspaceMembership.objects.create(
            workspace=ws,
            user=viewer,
            role=WorkspaceMembership.Role.VIEWER,
            status=WorkspaceMembership.Status.ACTIVE,
        )
        api_client.force_authenticate(viewer)

        resp = api_client.post(f"{_aws_base(ws.id)}{conn.id}/scan/")
        assert resp.status_code == 403, resp.data
