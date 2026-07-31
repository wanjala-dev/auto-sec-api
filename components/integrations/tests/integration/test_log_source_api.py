"""Integration tests for the WorkspaceLogSource CRUD + verify API (ADR 0008 Phase 3)."""

from __future__ import annotations

from unittest import mock

import pytest

from components.integrations.application.ports.log_source_port import LogSourceHealth

_ADAPTER = "components.integrations.infrastructure.adapters.log_sources.s3_log_source_adapter.S3LogSourceAdapter"


def _base(workspace_id):
    return f"/integrations/workspaces/{workspace_id}/log-sources/"


@pytest.fixture
def owner_ws(workspace_factory):
    ws = workspace_factory()
    return ws, ws.workspace_owner


def _connection(workspace, owner):
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    return AwsOrganizationConnection.objects.create(
        workspace=workspace,
        management_account_id="123456789012",
        role_name="AutoSecAuditRole",
        external_id=f"ext-{workspace.id}",
        status="connected",
        created_by=owner,
    )


@pytest.mark.django_db
class TestLogSourceCrud:
    def test_list_starts_empty(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.get(_base(ws.id))
        assert resp.status_code == 200
        assert resp.data["data"] == []

    def test_create_s3_source_starts_as_draft(self, api_client, owner_ws):
        ws, owner = owner_ws
        conn = _connection(ws, owner)
        api_client.force_authenticate(owner)
        resp = api_client.post(
            _base(ws.id),
            {"kind": "s3", "name": "prod trail", "config": {"aws_connection_id": str(conn.id), "bucket": "acme-logs"}},
            format="json",
        )
        assert resp.status_code == 201, resp.data
        assert resp.data["data"]["kind"] == "s3"
        assert resp.data["data"]["status"] == "draft"
        assert resp.data["data"]["config"]["bucket"] == "acme-logs"

    def test_create_rejects_s3_without_bucket(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(_base(ws.id), {"kind": "s3", "config": {"aws_connection_id": "x"}}, format="json")
        assert resp.status_code == 400
        assert "bucket" in resp.data["error"]

    def test_create_rejects_unavailable_kind(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(_base(ws.id), {"kind": "datadog", "config": {}}, format="json")
        assert resp.status_code == 400
        assert "not available" in resp.data["error"]

    def test_create_cloudwatch_source_starts_as_draft(self, api_client, owner_ws):
        ws, owner = owner_ws
        conn = _connection(ws, owner)
        api_client.force_authenticate(owner)
        resp = api_client.post(
            _base(ws.id),
            {
                "kind": "cloudwatch",
                "name": "lambda logs",
                "config": {
                    "aws_connection_id": str(conn.id),
                    "log_group": "/aws/lambda/acme",
                    "region": "us-east-1",
                },
            },
            format="json",
        )
        assert resp.status_code == 201, resp.data
        assert resp.data["data"]["kind"] == "cloudwatch"
        assert resp.data["data"]["status"] == "draft"
        assert resp.data["data"]["config"]["log_group"] == "/aws/lambda/acme"

    def test_create_cloudwatch_rejects_missing_log_group(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        resp = api_client.post(
            _base(ws.id), {"kind": "cloudwatch", "config": {"aws_connection_id": "x"}}, format="json"
        )
        assert resp.status_code == 400
        assert "log_group" in resp.data["error"]

    def test_patch_disable_then_enable(self, api_client, owner_ws):
        ws, owner = owner_ws
        conn = _connection(ws, owner)
        api_client.force_authenticate(owner)
        created = api_client.post(
            _base(ws.id),
            {"kind": "s3", "config": {"aws_connection_id": str(conn.id), "bucket": "b"}},
            format="json",
        ).data["data"]
        detail = f"{_base(ws.id)}{created['id']}/"

        disabled = api_client.patch(detail, {"status": "disabled"}, format="json")
        assert disabled.data["data"]["status"] == "disabled"
        enabled = api_client.patch(detail, {"status": "active"}, format="json")
        assert enabled.data["data"]["status"] == "active"

    def test_patch_rejects_system_owned_status(self, api_client, owner_ws):
        ws, owner = owner_ws
        conn = _connection(ws, owner)
        api_client.force_authenticate(owner)
        created = api_client.post(
            _base(ws.id),
            {"kind": "s3", "config": {"aws_connection_id": str(conn.id), "bucket": "b"}},
            format="json",
        ).data["data"]
        resp = api_client.patch(f"{_base(ws.id)}{created['id']}/", {"status": "draft"}, format="json")
        assert resp.status_code == 400

    def test_delete_removes_source(self, api_client, owner_ws):
        ws, owner = owner_ws
        conn = _connection(ws, owner)
        api_client.force_authenticate(owner)
        created = api_client.post(
            _base(ws.id),
            {"kind": "s3", "config": {"aws_connection_id": str(conn.id), "bucket": "b"}},
            format="json",
        ).data["data"]
        resp = api_client.delete(f"{_base(ws.id)}{created['id']}/")
        assert resp.status_code == 200
        assert api_client.get(_base(ws.id)).data["data"] == []

    def test_anonymous_is_denied(self, api_client, owner_ws):
        ws, _owner = owner_ws
        resp = api_client.get(_base(ws.id))
        assert resp.status_code in (401, 403)


@pytest.mark.django_db
class TestLogSourceVerify:
    def _create(self, api_client, ws, conn):
        return api_client.post(
            _base(ws.id),
            {"kind": "s3", "config": {"aws_connection_id": str(conn.id), "bucket": "acme-logs"}},
            format="json",
        ).data["data"]

    def test_verify_success_marks_active(self, api_client, owner_ws):
        ws, owner = owner_ws
        conn = _connection(ws, owner)
        api_client.force_authenticate(owner)
        created = self._create(api_client, ws, conn)

        url = f"{_base(ws.id)}{created['id']}/verify/"
        with mock.patch(f"{_ADAPTER}.verify", return_value=LogSourceHealth(ok=True)):
            resp = api_client.post(url, {}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "active"
        assert resp.data["data"]["last_verified_at"] is not None

    def test_verify_failure_marks_error(self, api_client, owner_ws):
        ws, owner = owner_ws
        conn = _connection(ws, owner)
        api_client.force_authenticate(owner)
        created = self._create(api_client, ws, conn)

        url = f"{_base(ws.id)}{created['id']}/verify/"
        with mock.patch(f"{_ADAPTER}.verify", return_value=LogSourceHealth(ok=False, detail="AccessDenied")):
            resp = api_client.post(url, {}, format="json")
        assert resp.data["data"]["status"] == "error"
        assert "AccessDenied" in resp.data["data"]["last_error"]

    def test_verify_missing_connection_marks_error(self, api_client, owner_ws):
        ws, owner = owner_ws
        api_client.force_authenticate(owner)
        # A source pointing at a non-existent connection id (never verified).
        resp = api_client.post(
            _base(ws.id),
            {"kind": "s3", "config": {"aws_connection_id": "11111111-1111-1111-1111-111111111111", "bucket": "b"}},
            format="json",
        )
        source_id = resp.data["data"]["id"]
        verified = api_client.post(f"{_base(ws.id)}{source_id}/verify/", {}, format="json")
        assert verified.data["data"]["status"] == "error"
        assert "AWS connection" in verified.data["data"]["last_error"]
