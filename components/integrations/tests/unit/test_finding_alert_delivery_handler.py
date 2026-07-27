"""Handler unit tests — severity gating + per-sink delivery, with a fake sink port."""

from __future__ import annotations

import uuid

import pytest

from components.integrations.application.handlers import finding_alert_delivery_handler as h
from components.integrations.application.ports.alert_sink_port import SlackSink
from components.shared_kernel.domain.events import FindingRaised

pytestmark = pytest.mark.unit


class _FakePort:
    def __init__(self, sinks):
        self._sinks = sinks
        self.delivered: list[tuple] = []

    def enabled_slack_sinks(self, workspace_id):
        return self._sinks

    def deliver(self, sink, message):
        self.delivered.append((sink, message))
        return True


def _event(severity="critical"):
    return FindingRaised(
        workspace_id=uuid.uuid4(),
        finding_id=uuid.uuid4(),
        fingerprint="fp-1",
        asset_urn="arn:aws:s3:::secret-bucket",
        severity=severity,
        status="open",
        source="cloud_posture.prowler",
        title="Public S3 bucket",
        is_new=True,
    )


def _sink(min_severity="high"):
    return SlackSink(id=uuid.uuid4(), channel="#soc", min_severity=min_severity, token="xoxb-tok")


def _wire(monkeypatch, port):
    monkeypatch.setattr(h, "get_alert_sink_port", lambda: port)


def test_delivers_to_qualifying_sinks(monkeypatch):
    port = _FakePort([_sink(min_severity="high")])
    _wire(monkeypatch, port)
    h.deliver_finding_to_slack(_event("critical"))
    assert len(port.delivered) == 1
    _, message = port.delivered[0]
    assert "Public S3 bucket" in message.title
    assert "secret-bucket" in message.text


def test_respects_per_sink_min_severity(monkeypatch):
    high_sink = _sink(min_severity="high")
    crit_sink = _sink(min_severity="critical")
    port = _FakePort([high_sink, crit_sink])
    _wire(monkeypatch, port)
    h.deliver_finding_to_slack(_event("high"))  # meets high, not critical
    delivered_ids = [s.id for s, _ in port.delivered]
    assert high_sink.id in delivered_ids
    assert crit_sink.id not in delivered_ids


def test_no_sinks_is_a_noop(monkeypatch):
    port = _FakePort([])
    _wire(monkeypatch, port)
    h.deliver_finding_to_slack(_event("critical"))  # must not raise
    assert port.delivered == []
