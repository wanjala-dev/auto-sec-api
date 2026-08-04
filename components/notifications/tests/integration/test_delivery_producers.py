"""The producer side of the external funnel (ADR 0016) — the dispatches that feed it.

PR #246 built the leg and retired the direct ``FindingRaised → Slack`` handler;
these tests pin the restored producers end to end (handler → dispatch → external
leg → adapter): a critical NEW finding alerts individually, a completed scan
digests ONCE per run, a failed scan alerts, and steady-state noise (re-observations,
non-criticals) stays silent.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.integrations.application.providers.secret_envelope_provider import encrypt_secret
from components.notifications.application.handlers.finding_raised_alert_handler import (
    handle_finding_raised_alert,
)
from components.notifications.application.handlers.scan_event_alert_handler import (
    handle_scan_completed,
    handle_scan_failed,
)
from components.shared_kernel.domain.delivery_events import (
    FINDING_CRITICAL,
    SCAN_DIGEST,
    SCAN_FAILED,
)
from components.shared_kernel.domain.events import FindingRaised, ScanCompleted, ScanFailed

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_WEBHOOK = "https://hooks.slack.com/services/T0/B0/abcdefghijklmnop"


def _connection(workspace, **overrides):
    from infrastructure.persistence.integrations.models import DeliveryConnection

    defaults = dict(
        workspace=workspace,
        kind=DeliveryConnection.Kind.SLACK,
        name="Sec alerts",
        auth_mode=DeliveryConnection.AuthMode.WEBHOOK_URL,
        secret_ciphertext=encrypt_secret(_WEBHOOK),
        min_severity="high",
        events=[FINDING_CRITICAL, SCAN_DIGEST, SCAN_FAILED],
        is_enabled=True,
    )
    defaults.update(overrides)
    return DeliveryConnection.objects.create(**defaults)


class _Recorder:
    """Stands in for the Slack adapter so nothing leaves the test."""

    def __init__(self):
        from components.integrations.application.ports.delivery_channel_port import DeliveryResult

        self.result = DeliveryResult(ok=True)
        self.calls: list = []

    def deliver(self, connection, message):
        self.calls.append((connection, message))
        return self.result

    def verify(self, connection):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def slack(monkeypatch):
    """Patch the delivery provider at its source module (the task imports it lazily)."""
    import components.integrations.application.providers.delivery_channel_provider as provider_mod

    recorder = _Recorder()

    class _Provider:
        def get(self, kind):
            return recorder

    monkeypatch.setattr(provider_mod, "get_delivery_channel_provider", lambda: _Provider())
    return recorder


def _finding_raised(workspace, **overrides):
    defaults = dict(
        workspace_id=workspace.id,
        finding_id=uuid4(),
        fingerprint="fp-1",
        asset_urn="arn:aws:s3:::bucket",
        severity="critical",
        status="open",
        source="cloud_posture.prowler",
        title="Public S3 bucket",
        is_new=True,
    )
    defaults.update(overrides)
    return FindingRaised(**defaults)


def _external_rows(workspace):
    from infrastructure.persistence.notifications.models import ExternalDelivery

    return ExternalDelivery.objects.filter(connection__workspace=workspace)


class TestFindingFiledProducer:
    def test_critical_new_finding_delivers_exactly_one_alert(
        self, workspace_factory, slack, django_capture_on_commit_callbacks
    ):
        workspace = workspace_factory()
        _connection(workspace)
        event = _finding_raised(workspace, vulnerability_id="CVE-2024-1234", package="openssl")

        with django_capture_on_commit_callbacks(execute=True):
            handle_finding_raised_alert(event)

        assert len(slack.calls) == 1
        _, message = slack.calls[0]
        assert "Critical finding" in message.title
        assert "Public S3 bucket" in message.title
        # #247: the vulnerability identity travels (allowlisted, not leaked wholesale).
        assert message.fields.get("vulnerability_id") == "CVE-2024-1234"
        assert message.fields.get("package") == "openssl"
        # The deep link is absolutized for the chat channel and lands on the finding.
        assert message.link.startswith("http")
        assert f"?panel=findings&finding={event.finding_id}" in message.link
        assert _external_rows(workspace).filter(status="sent").count() == 1

    def test_non_critical_new_finding_stays_silent(self, workspace_factory, slack, django_capture_on_commit_callbacks):
        workspace = workspace_factory()
        _connection(workspace)

        with django_capture_on_commit_callbacks(execute=True):
            handle_finding_raised_alert(_finding_raised(workspace, severity="high"))

        assert slack.calls == []
        assert _external_rows(workspace).count() == 0, "a non-critical must not even dispatch"

    def test_re_observation_stays_silent(self, workspace_factory, slack, django_capture_on_commit_callbacks):
        workspace = workspace_factory()
        _connection(workspace)

        with django_capture_on_commit_callbacks(execute=True):
            handle_finding_raised_alert(_finding_raised(workspace, is_new=False))

        assert slack.calls == []
        assert _external_rows(workspace).count() == 0


class TestScanDigestProducer:
    def _completed(self, workspace, **overrides):
        defaults = dict(
            workspace_id=workspace.id,
            source="cloud_posture.prowler",
            engine="prowler",
            scan_id=str(uuid4()),
            target_ref="123456789012",
            account_id="123456789012",
            total_checks=150,
            findings_observed=149,
            critical=3,
            high=20,
            medium=100,
            low=26,
        )
        defaults.update(overrides)
        return ScanCompleted(**defaults)

    def test_scan_completed_delivers_one_digest_with_counts(
        self, workspace_factory, slack, django_capture_on_commit_callbacks
    ):
        workspace = workspace_factory()
        _connection(workspace)

        with django_capture_on_commit_callbacks(execute=True):
            handle_scan_completed(self._completed(workspace))

        assert len(slack.calls) == 1
        _, message = slack.calls[0]
        assert "scan completed" in message.title
        assert "3 critical" in message.body
        assert "20 high" in message.body

    def test_redelivered_digest_does_not_double_post(
        self, workspace_factory, slack, django_capture_on_commit_callbacks
    ):
        """ONE message per scan run — a redelivery converges on the ledger."""
        workspace = workspace_factory()
        _connection(workspace)
        event = self._completed(workspace)

        with django_capture_on_commit_callbacks(execute=True):
            handle_scan_completed(event)
        with django_capture_on_commit_callbacks(execute=True):
            handle_scan_completed(event)

        assert len(slack.calls) == 1, "the same scan digest was posted twice"

    def test_clean_scan_still_digests(self, workspace_factory, slack, django_capture_on_commit_callbacks):
        workspace = workspace_factory()
        _connection(workspace)

        with django_capture_on_commit_callbacks(execute=True):
            handle_scan_completed(self._completed(workspace, findings_observed=0, critical=0, high=0, medium=0, low=0))

        assert len(slack.calls) == 1
        _, message = slack.calls[0]
        assert "No new findings" in message.body


class TestScanFailedProducer:
    def test_scan_failed_alerts(self, workspace_factory, slack, django_capture_on_commit_callbacks):
        workspace = workspace_factory()
        _connection(workspace)

        with django_capture_on_commit_callbacks(execute=True):
            handle_scan_failed(
                ScanFailed(
                    workspace_id=workspace.id,
                    source="container_security.trivy",
                    engine="trivy",
                    run_id=str(uuid4()),
                    target_ref="repo/image:tag",
                    account_id="123456789012",
                    reason="scan engine failure",
                )
            )

        assert len(slack.calls) == 1
        _, message = slack.calls[0]
        assert "Scan failed" in message.title
        assert message.fields.get("reason") == "scan engine failure"

    def test_unsubscribed_connection_is_skipped_with_reason(
        self, workspace_factory, slack, django_capture_on_commit_callbacks
    ):
        """The dispatch still happens (SSOT of 'what fired'); the connection's
        subscription list decides delivery — recorded truthfully on the ledger."""
        workspace = workspace_factory()
        _connection(workspace, events=[FINDING_CRITICAL])  # not subscribed to scan events

        with django_capture_on_commit_callbacks(execute=True):
            handle_scan_failed(
                ScanFailed(
                    workspace_id=workspace.id,
                    source="cloud_posture.prowler",
                    engine="prowler",
                    run_id=str(uuid4()),
                    account_id="123456789012",
                )
            )

        assert slack.calls == []
        row = _external_rows(workspace).get()
        assert row.status == "skipped"
