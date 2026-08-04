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


def _event(severity="critical", *, is_new=True):
    return FindingRaised(
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


def test_failed_delivery_is_recorded_on_the_connection(monkeypatch):
    repository = _FakeRepository([_connection()])
    adapter = _FakeAdapter(DeliveryResult(ok=False, detail="channel_not_found", permanent=True))
    _wire(monkeypatch, repository, adapter)

    h.deliver_finding_to_slack(_event("critical"))

    assert repository.delivered_ids == []
    assert repository.errored == [(repository.connections[0].id, "channel_not_found")]
