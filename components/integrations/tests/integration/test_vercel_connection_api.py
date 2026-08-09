"""End-to-end API tests for the Vercel posture loop (ADR 0021 D2/D3/D4/D6).

Drives the REAL controller chain, stubbing only the live seams:

    POST   …/vercel-connections/              create → 201 (flag-gated 403 while dark)
    POST   …/vercel-connections/<id>/verify/  VercelApiPort stubbed → team trio recorded
    POST   …/vercel-connections/<id>/scan/    gate → eager Celery → the generic run_scan
                                              → REAL ProwlerScanner on canned Vercel OCSF
                                              → ScanRun + urn:vercel: Findings in the SSOT

Plus the dark-launch wall (feature.vercel_posture, D6) and the cooldown budget (D3).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.cache import cache

from components.integrations.application.ports.vercel_api_port import VercelHealth, VercelTeam
from infrastructure.persistence.findings.models import Finding
from infrastructure.persistence.integrations.models import VercelConnection
from infrastructure.persistence.scanning.models import ScanRun

_TEAM_ID = "team_abc123DEF456"
_ADAPTER_FACTORY = "components.integrations.application.providers.vercel_provider.get_vercel_api_adapter"
_BACKEND_PROVIDER = "components.scanning.application.providers.execution_backend_provider.build_execution_backend"

_VERCEL_FIXTURE = (
    Path(__file__).resolve().parents[3] / "cloud_posture" / "tests" / "fixtures" / "prowler_vercel_ocsf_sample.json"
)


def _base(ws_id) -> str:
    return f"/integrations/workspaces/{ws_id}/vercel-connections/"


def _stub_adapter(*, token_ok=True, team=None, expiry=None):
    adapter = mock.Mock()
    adapter.verify_token.return_value = VercelHealth(ok=token_ok, detail="" if token_ok else "The token is invalid.")
    if team is None:
        team = VercelTeam(id=_TEAM_ID, slug="acme", name="Acme")
    adapter.get_team.return_value = (VercelHealth(ok=True), team)
    adapter.get_token_expiry.return_value = expiry
    return adapter


@pytest.fixture(autouse=True)
def _clean_gate_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def vercel_ws(workspace_factory):
    ws = workspace_factory()
    return SimpleNamespace(workspace=ws, owner=ws.workspace_owner)


@pytest.mark.integration
@pytest.mark.django_db
class TestVercelConnectionLifecycle:
    def _create(self, api_client, ws, *, team=_TEAM_ID, token="vc_e2e_token"):
        return api_client.post(_base(ws.id), {"team": team, "token": token, "name": "Acme"}, format="json")

    def test_create_stores_the_token_encrypted_and_never_echoes_it(self, api_client, vercel_ws):
        api_client.force_authenticate(vercel_ws.owner)
        resp = self._create(api_client, vercel_ws.workspace)
        assert resp.status_code == 201, resp.data
        body = resp.data["data"]
        assert body["team_id"] == _TEAM_ID
        assert body["has_token"] is True
        assert "token" not in body and "token_ciphertext" not in body

        connection = VercelConnection.objects.get(id=body["id"])
        assert connection.token_ciphertext
        assert "vc_e2e_token" not in connection.token_ciphertext  # encrypted, never plaintext

    def test_create_rejects_a_malformed_team(self, api_client, vercel_ws):
        api_client.force_authenticate(vercel_ws.owner)
        resp = self._create(api_client, vercel_ws.workspace, team="not a team!")
        assert resp.status_code == 400, resp.data

    def test_verify_records_the_canonical_team_trio(self, api_client, vercel_ws):
        api_client.force_authenticate(vercel_ws.owner)
        created = self._create(api_client, vercel_ws.workspace, team="acme").data["data"]

        with mock.patch(_ADAPTER_FACTORY, return_value=_stub_adapter()):
            resp = api_client.post(f"{_base(vercel_ws.workspace.id)}{created['id']}/verify/")

        assert resp.status_code == 200, resp.data
        body = resp.data["data"]
        assert body["status"] == "connected"
        assert body["team_id"] == _TEAM_ID
        assert body["team_slug"] == "acme"
        assert body["team_name"] == "Acme"
        assert body["last_verified_at"] is not None

    def test_verify_with_a_revoked_token_marks_error_loudly(self, api_client, vercel_ws):
        # The ADR 0008 silent-blank lesson: a dead token is a LOUD connection-health
        # error, never a quietly empty next scan.
        api_client.force_authenticate(vercel_ws.owner)
        created = self._create(api_client, vercel_ws.workspace).data["data"]

        with mock.patch(_ADAPTER_FACTORY, return_value=_stub_adapter(token_ok=False)):
            resp = api_client.post(f"{_base(vercel_ws.workspace.id)}{created['id']}/verify/")

        assert resp.status_code == 200
        assert resp.data["data"]["status"] == "error"
        assert "invalid" in resp.data["data"]["last_error"]

    def test_update_and_delete(self, api_client, vercel_ws):
        api_client.force_authenticate(vercel_ws.owner)
        created = self._create(api_client, vercel_ws.workspace).data["data"]
        detail = f"{_base(vercel_ws.workspace.id)}{created['id']}/"

        resp = api_client.patch(detail, {"status": "disabled"}, format="json")
        assert resp.status_code == 200 and resp.data["data"]["status"] == "disabled"

        resp = api_client.delete(detail)
        assert resp.status_code == 200 and resp.data["deleted"] is True
        assert not VercelConnection.objects.filter(id=created["id"]).exists()


@pytest.mark.integration
@pytest.mark.django_db
class TestVercelScanEndToEnd:
    """Scan-now → the scanning SPINE → urn:vercel: findings in the SSOT (hermetic)."""

    def _connected(self, ws, owner) -> VercelConnection:
        from components.integrations.application.providers.secret_envelope_provider import encrypt_secret

        return VercelConnection.objects.create(
            workspace=ws,
            team_id=_TEAM_ID,
            team_slug="acme",
            token_ciphertext=encrypt_secret("vc_e2e_token"),
            status=VercelConnection.Status.CONNECTED,
            created_by=owner,
        )

    def test_scan_records_a_run_and_lands_vercel_findings(
        self, api_client, vercel_ws, django_capture_on_commit_callbacks
    ):
        from components.cloud_posture.tests._prowler_backend_stub import RecordsBackend

        ws, owner = vercel_ws.workspace, vercel_ws.owner
        api_client.force_authenticate(owner)
        connection = self._connected(ws, owner)

        backend = RecordsBackend(json.loads(_VERCEL_FIXTURE.read_text()))
        with (
            mock.patch(_BACKEND_PROVIDER, return_value=backend),
            django_capture_on_commit_callbacks(execute=True),
        ):
            resp = api_client.post(f"{_base(ws.id)}{connection.id}/scan/")

        assert resp.status_code == 202, resp.data

        # The engine ran once, pinned to the connection's team, token env-only.
        assert len(backend.calls) == 1
        spec = backend.calls[0]
        assert spec.secret_env == {"VERCEL_TOKEN": "vc_e2e_token", "VERCEL_TEAM": _TEAM_ID}

        # SPINE provenance: a COMPLETED ScanRun with trigger + triggering user.
        run = ScanRun.objects.get(workspace=ws, source="cloud_posture.prowler.vercel")
        assert run.status == ScanRun.Status.COMPLETED
        assert run.target_ref == _TEAM_ID
        assert run.trigger == "manual"
        assert str(run.triggered_by_id) == str(owner.id)
        assert run.total_checks == 4 and run.failed_count == 2

        # SSOT: the 3 actionable findings, vercel-namespaced, run-stamped.
        findings = Finding.objects.filter(workspace=ws, source="cloud_posture.prowler.vercel")
        assert findings.count() == 3
        for finding in findings:
            assert finding.asset_urn.startswith("urn:vercel:") or finding.asset_urn.startswith(f"urn:vercel:{_TEAM_ID}")
            assert finding.attributes["team_id"] == _TEAM_ID
            assert finding.attributes["scan_run_id"] == str(run.id)
        # The MANUAL firewall check surfaced honestly (not PASS, not vanished).
        manual = findings.get(attributes__check_id="security_waf_enabled")
        assert manual.attributes["check_status"] == "manual"

    def test_second_scan_within_the_cooldown_is_429(self, api_client, vercel_ws, django_capture_on_commit_callbacks):
        from components.cloud_posture.tests._prowler_backend_stub import RecordsBackend

        ws, owner = vercel_ws.workspace, vercel_ws.owner
        api_client.force_authenticate(owner)
        connection = self._connected(ws, owner)

        backend = RecordsBackend(json.loads(_VERCEL_FIXTURE.read_text()))
        with (
            mock.patch(_BACKEND_PROVIDER, return_value=backend),
            django_capture_on_commit_callbacks(execute=True),
        ):
            first = api_client.post(f"{_base(ws.id)}{connection.id}/scan/")
            second = api_client.post(f"{_base(ws.id)}{connection.id}/scan/")

        assert first.status_code == 202
        assert second.status_code == 429, second.data
        assert second.data["error"] in ("scan_cooldown", "scan_already_running")

    def test_scan_of_a_disabled_connection_is_409(self, api_client, vercel_ws):
        ws, owner = vercel_ws.workspace, vercel_ws.owner
        api_client.force_authenticate(owner)
        connection = self._connected(ws, owner)
        connection.status = VercelConnection.Status.DISABLED
        connection.save(update_fields=["status"])

        resp = api_client.post(f"{_base(ws.id)}{connection.id}/scan/")
        assert resp.status_code == 409, resp.data


@pytest.mark.integration
@pytest.mark.django_db
class TestVercelDarkLaunchWall:
    """D6: the pillar ships dark — create + scan are flag-walled, fail closed."""

    @pytest.mark.real_feature_flags
    def test_create_403_while_the_flag_is_off(self, api_client, vercel_ws):
        # Real flag cascade + no seeded feature.vercel_posture row → the gate is off.
        api_client.force_authenticate(vercel_ws.owner)
        resp = api_client.post(_base(vercel_ws.workspace.id), {"team": _TEAM_ID, "token": "vc_tok"}, format="json")
        assert resp.status_code == 403, resp.data
        assert resp.data["error"] == "vercel_posture_not_enabled"

    @pytest.mark.real_feature_flags
    def test_scan_403_while_the_flag_is_off(self, api_client, vercel_ws):
        from components.integrations.application.providers.secret_envelope_provider import encrypt_secret

        ws, owner = vercel_ws.workspace, vercel_ws.owner
        connection = VercelConnection.objects.create(
            workspace=ws,
            team_id=_TEAM_ID,
            token_ciphertext=encrypt_secret("vc_tok"),
            status=VercelConnection.Status.CONNECTED,
        )
        api_client.force_authenticate(owner)
        resp = api_client.post(f"{_base(ws.id)}{connection.id}/scan/")
        assert resp.status_code == 403, resp.data
        assert resp.data["error"] == "vercel_posture_not_enabled"

    @pytest.mark.real_feature_flags
    def test_list_still_works_while_dark_so_operators_can_manage_rows(self, api_client, vercel_ws):
        api_client.force_authenticate(vercel_ws.owner)
        resp = api_client.get(_base(vercel_ws.workspace.id))
        assert resp.status_code == 200 and resp.data["data"] == []
