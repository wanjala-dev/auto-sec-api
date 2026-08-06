"""Backbone Slack fan-out chain — the walk Henry demoed live, end to end.

One hermetic sequence, all REAL endpoints and the REAL event spine, stubbing only
the outermost boundaries (STS, the scan backend, the Slack HTTP post):

    POST …/delivery-connections/          Slack sink created (default event subs)
    POST …/delivery-connections/<id>/verify/   adapter HTTP stubbed → connected
    POST …/aws/ → …/verify/ → …/scan/     the #228 loop, with a CRITICAL record

and asserts the whole fan-out of that one scan:

    * the Finding lands in the SSOT (critical, open),
    * the board gets the local-copy card (``ai.cloud_posture`` Task) — the
      in-app/provenance side effect (FindingRaised → finding_raised_board),
    * the external leg delivers BOTH messages: the individual critical-finding
      alert AND the one-per-scan digest (FindingRaised + ScanCompleted →
      dispatch → ``deliver_external`` → Slack adapter), each ledgered as sent,
    * a re-observation scan (same fingerprint) posts NO second critical alert —
      only another digest (the ADR 0016 anti-flood line).

Lives in integrations (the driving surface + the seam stubs live here); the
producer/leg unit behaviors are pinned in components/notifications tests.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_MGMT_ACCOUNT = "123456789012"
_WEBHOOK = "https://hooks.slack.com/services/T000/B000/abcdefghijklmnop"

CRITICAL_OCSF_RECORDS: list[dict] = [
    {
        "metadata": {"event_code": "iam_root_access_key_exists"},
        "severity": "Critical",
        "status_code": "FAIL",
        "finding_info": {"uid": "u-e2e-crit-1", "title": "Root account has active access keys"},
        "resources": [
            {
                "uid": "arn:aws:iam::123456789012:root",
                "name": "root",
                "type": "AwsIamUser",
                "region": "us-east-1",
                "group": {"name": "iam"},
            }
        ],
        "cloud": {"account": {"uid": _MGMT_ACCOUNT}, "region": "us-east-1"},
        "remediation": {"desc": "Delete the root access keys."},
    }
]


class _SlackRecorder:
    """Stands in for the Slack delivery adapter so nothing leaves the test
    (mirrors the #248 producer-suite recorder)."""

    def __init__(self):
        from components.integrations.application.ports.delivery_channel_port import DeliveryResult

        self.result = DeliveryResult(ok=True)
        self.calls: list = []

    def deliver(self, connection, message):
        self.calls.append((connection, message))
        return self.result

    def verify(self, connection):
        from components.integrations.application.ports.delivery_channel_port import DeliveryHealth

        return DeliveryHealth(ok=True, detail="stubbed reachable")


@pytest.fixture
def slack(monkeypatch):
    """Patch the delivery provider at its source module (the task imports it lazily)."""
    import components.integrations.application.providers.delivery_channel_provider as provider_mod

    recorder = _SlackRecorder()

    class _Provider:
        def get(self, kind):
            return recorder

    monkeypatch.setattr(provider_mod, "get_delivery_channel_provider", lambda: _Provider())
    return recorder


def _connect_slack(api_client, ws) -> dict:
    """Create + verify the Slack delivery connection through the REAL endpoints.
    The ``slack`` fixture's provider patch serves the verify probe too, so nothing
    reaches Slack."""
    base = f"/integrations/workspaces/{ws.id}/delivery-connections/"
    created = api_client.post(
        base,
        {"kind": "slack", "name": "Sec alerts", "auth_mode": "webhook_url", "secret": _WEBHOOK},
        format="json",
    )
    assert created.status_code == 201, created.data
    connection = created.data["data"]
    # Default subscriptions cover the backbone events (finding_critical + scan digest).
    assert "finding_critical" in connection["events"]
    assert "scan_digest" in connection["events"]

    verified = api_client.post(f"{base}{connection['id']}/verify/", format="json")
    assert verified.status_code == 200, verified.data
    assert verified.data["data"]["status"] == "connected"
    return connection


def _run_scan(api_client, ws, conn_id, stub_scan_execution, django_capture_on_commit_callbacks, records):
    with (
        stub_scan_execution(records=records),
        django_capture_on_commit_callbacks(execute=True),
    ):
        resp = api_client.post(f"/integrations/workspaces/{ws.id}/aws/{conn_id}/scan/")
    assert resp.status_code == 202, resp.data
    return resp


class TestBackboneSlackFanoutChain:
    def test_scan_fans_out_to_board_and_slack(
        self,
        api_client,
        integrations_workspace,
        stub_org_verification,
        stub_scan_execution,
        django_capture_on_commit_callbacks,
        slack,
        monkeypatch,
    ):
        ws, owner = integrations_workspace.workspace, integrations_workspace.owner
        api_client.force_authenticate(owner)

        # 1. Slack sink connected through the endpoints.
        _connect_slack(api_client, ws)

        # 2. AWS connect → verify → scan (the #228 loop) with ONE critical record.
        created = api_client.post(
            f"/integrations/workspaces/{ws.id}/aws/",
            {"management_account_id": _MGMT_ACCOUNT, "name": "Acme Org"},
            format="json",
        ).data["data"]
        with stub_org_verification(accounts=[{"id": _MGMT_ACCOUNT, "name": "Prod"}]):
            api_client.post(f"/integrations/workspaces/{ws.id}/aws/{created['id']}/verify/")
        _run_scan(
            api_client,
            ws,
            created["id"],
            stub_scan_execution,
            django_capture_on_commit_callbacks,
            CRITICAL_OCSF_RECORDS,
        )

        # 3. The SSOT row.
        from infrastructure.persistence.findings.models import Finding

        finding = Finding.objects.get(workspace=ws, source="cloud_posture.prowler")
        assert finding.severity == "critical"
        assert finding.status == "open"

        # 4. The board side effect — the local-copy card the HUD renders
        #    (FindingRaised → finding_raised_board_handler → persist_finding_as_task).
        from infrastructure.persistence.project.models import Task

        card = Task.objects.get(workspace=ws, source_type="ai.cloud_posture")
        assert card.metadata["payload"]["finding_id"] == str(finding.id)
        assert "Critical" in card.title

        # 5. The external leg: exactly TWO Slack messages — the individual
        #    critical alert + the one-per-scan digest — both ledgered as sent.
        assert len(slack.calls) == 2, [m.title for _, m in slack.calls]
        titles = sorted(message.title for _, message in slack.calls)
        assert any("Critical finding" in t for t in titles), titles
        assert any("scan completed" in t for t in titles), titles

        alert = next(m for _, m in slack.calls if "Critical finding" in m.title)
        assert f"?panel=findings&finding={finding.id}" in alert.link
        assert alert.fields.get("severity") == "critical"

        from infrastructure.persistence.notifications.models import ExternalDelivery

        sent = ExternalDelivery.objects.filter(connection__workspace=ws, status="sent")
        assert sent.count() == 2

    def test_rescan_digests_again_but_never_re_alerts_the_same_finding(
        self,
        api_client,
        integrations_workspace,
        stub_org_verification,
        stub_scan_execution,
        django_capture_on_commit_callbacks,
        slack,
        monkeypatch,
    ):
        """The anti-flood contract on the SAME walk: a nightly re-scan re-observes
        the fingerprint (is_new=False) → no second critical alert; the digest
        still lands (a new scan_id per run)."""
        ws, owner = integrations_workspace.workspace, integrations_workspace.owner
        api_client.force_authenticate(owner)
        _connect_slack(api_client, ws)

        created = api_client.post(
            f"/integrations/workspaces/{ws.id}/aws/",
            {"management_account_id": _MGMT_ACCOUNT, "name": "Acme Org"},
            format="json",
        ).data["data"]
        with stub_org_verification(accounts=[{"id": _MGMT_ACCOUNT, "name": "Prod"}]):
            api_client.post(f"/integrations/workspaces/{ws.id}/aws/{created['id']}/verify/")

        _run_scan(
            api_client,
            ws,
            created["id"],
            stub_scan_execution,
            django_capture_on_commit_callbacks,
            CRITICAL_OCSF_RECORDS,
        )
        _run_scan(
            api_client,
            ws,
            created["id"],
            stub_scan_execution,
            django_capture_on_commit_callbacks,
            CRITICAL_OCSF_RECORDS,
        )

        titles = [message.title for _, message in slack.calls]
        assert sum("Critical finding" in t for t in titles) == 1, titles
        assert sum("scan completed" in t for t in titles) == 2, titles

        # Still ONE SSOT row and ONE board card — the re-scan updated, not duplicated.
        from infrastructure.persistence.findings.models import Finding
        from infrastructure.persistence.project.models import Task

        assert Finding.objects.filter(workspace=ws, source="cloud_posture.prowler").count() == 1
        assert Task.objects.filter(workspace=ws, source_type="ai.cloud_posture").count() == 1
