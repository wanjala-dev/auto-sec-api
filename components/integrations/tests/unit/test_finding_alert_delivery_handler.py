"""Handler unit tests — severity gating, new-only gating, and per-connection delivery.

Fakes the repository + provider seam rather than the ORM, so these stay unit tests.
The handler is retired by ADR 0016 P1 step 4; these assertions move to the funnel
leg with it.
"""

from __future__ import annotations

import uuid

import pytest

from components.integrations.application.handlers import finding_alert_delivery_handler as h
from components.integrations.application.ports.delivery_channel_port import (
    DeliveryResult,
    ResolvedDeliveryConnection,
)
from components.shared_kernel.domain.events import FindingRaised

pytestmark = pytest.mark.unit


class _FakeRepository:
    def __init__(self, connections):
        self.connections = connections
        self.delivered_ids: list = []
        self.errored: list[tuple] = []

    def enabled_for_workspace(self, workspace_id, *, kind=None):
        return self.connections

    def mark_delivered(self, connection_id):
        self.delivered_ids.append(connection_id)

    def mark_error(self, connection_id, error):
        self.errored.append((connection_id, error))


class _FakeAdapter:
    def __init__(self, result=None):
        self._result = result or DeliveryResult(ok=True)
        self.calls: list[tuple] = []

    def deliver(self, connection, message):
        self.calls.append((connection, message))
        return self._result

    def verify(self, connection):  # pragma: no cover - not exercised here
        raise NotImplementedError


class _FakeProvider:
    def __init__(self, adapter):
        self._adapter = adapter

    def get(self, kind):
        return self._adapter


def _event(severity="critical", *, is_new=True, **overrides):
    kwargs = dict(
        workspace_id=uuid.uuid4(),
        finding_id=uuid.uuid4(),
        fingerprint="fp-1",
        asset_urn="arn:aws:s3:::secret-bucket",
        severity=severity,
        status="open",
        source="cloud_posture.prowler",
        title="Public S3 bucket",
        is_new=is_new,
    )
    kwargs.update(overrides)
    return FindingRaised(**kwargs)


def _connection(min_severity="high"):
    return ResolvedDeliveryConnection(
        id=uuid.uuid4(),
        kind="slack",
        auth_mode="bot_token",
        secret="xoxb-tok",
        channel="#soc",
        min_severity=min_severity,
    )


def _wire(monkeypatch, repository, adapter):
    monkeypatch.setattr(h, "get_delivery_connection_repository", lambda: repository)
    monkeypatch.setattr(h, "get_delivery_channel_provider", lambda: _FakeProvider(adapter))


def test_delivers_to_qualifying_connections(monkeypatch):
    repository, adapter = _FakeRepository([_connection(min_severity="high")]), _FakeAdapter()
    _wire(monkeypatch, repository, adapter)

    h.deliver_finding_to_slack(_event("critical"))

    assert len(adapter.calls) == 1
    _, message = adapter.calls[0]
    assert "Public S3 bucket" in message.title
    assert "secret-bucket" in message.body
    assert repository.delivered_ids == [repository.connections[0].id]


def test_respects_per_connection_min_severity(monkeypatch):
    high_connection = _connection(min_severity="high")
    critical_connection = _connection(min_severity="critical")
    repository = _FakeRepository([high_connection, critical_connection])
    adapter = _FakeAdapter()
    _wire(monkeypatch, repository, adapter)

    h.deliver_finding_to_slack(_event("high"))  # meets high, not critical

    delivered = [connection.id for connection, _ in adapter.calls]
    assert high_connection.id in delivered
    assert critical_connection.id not in delivered


def test_skips_re_observations_of_an_open_finding(monkeypatch):
    """Steady-state noise is the exact failure mode ``is_new`` exists to prevent."""
    repository, adapter = _FakeRepository([_connection()]), _FakeAdapter()
    _wire(monkeypatch, repository, adapter)

    h.deliver_finding_to_slack(_event("critical", is_new=False))

    assert adapter.calls == []


def test_no_connections_is_a_noop(monkeypatch):
    repository, adapter = _FakeRepository([]), _FakeAdapter()
    _wire(monkeypatch, repository, adapter)

    h.deliver_finding_to_slack(_event("critical"))  # must not raise

    assert adapter.calls == []


def test_message_carries_hud_deep_link(monkeypatch, settings):
    """Every alert deep-links the HUD open on ITS finding (?panel=findings&finding=<id>)."""
    settings.FRONTEND_URL = "https://hud.example"
    repository, adapter = _FakeRepository([_connection()]), _FakeAdapter()
    _wire(monkeypatch, repository, adapter)

    event = _event("critical")
    h.deliver_finding_to_slack(event)

    _, message = adapter.calls[0]
    assert message.link == (f"https://hud.example/ai/v2/{event.workspace_id}?panel=findings&finding={event.finding_id}")


def test_no_frontend_base_means_no_link(monkeypatch, settings):
    """An unconfigured frontend base renders a link-less message, never a broken URL."""
    settings.FRONTEND_URL = ""
    settings.LOCALHOST_FRONTEND_URL = ""
    repository, adapter = _FakeRepository([_connection()]), _FakeAdapter()
    _wire(monkeypatch, repository, adapter)

    h.deliver_finding_to_slack(_event("critical"))

    _, message = adapter.calls[0]
    assert message.link == ""


def test_message_body_carries_cve_and_package_when_available(monkeypatch):
    """Twin titles ("CVE-… in openssl" across images) stay distinguishable."""
    repository, adapter = _FakeRepository([_connection()]), _FakeAdapter()
    _wire(monkeypatch, repository, adapter)

    h.deliver_finding_to_slack(_event("critical", vulnerability_id="CVE-2025-12345", package="openssl"))

    _, message = adapter.calls[0]
    assert "CVE-2025-12345" in message.body
    assert "openssl" in message.body


def test_message_stays_notification_grade(monkeypatch, settings):
    """Redaction standard (ADR 0016 D6): id/title/severity/asset/source/status/vuln/link
    only — never a raw payload, attributes bag, or description dump."""
    settings.FRONTEND_URL = "https://hud.example"
    repository, adapter = _FakeRepository([_connection()]), _FakeAdapter()
    _wire(monkeypatch, repository, adapter)

    event = _event("critical", vulnerability_id="CVE-2025-12345", package="openssl")
    h.deliver_finding_to_slack(event)

    _, message = adapter.calls[0]
    allowed_prefixes = ("Vulnerability: ", "Asset: ", "Source: ", "Status: ")
    for line in message.body.splitlines():
        assert line.startswith(allowed_prefixes), f"unexpected body line: {line!r}"
    assert message.fields == {}


def test_failed_delivery_is_recorded_on_the_connection(monkeypatch):
    repository = _FakeRepository([_connection()])
    adapter = _FakeAdapter(DeliveryResult(ok=False, detail="channel_not_found", permanent=True))
    _wire(monkeypatch, repository, adapter)

    h.deliver_finding_to_slack(_event("critical"))

    assert repository.delivered_ids == []
    assert repository.errored == [(repository.connections[0].id, "channel_not_found")]
