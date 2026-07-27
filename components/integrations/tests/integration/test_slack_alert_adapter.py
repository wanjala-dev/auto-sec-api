"""Slack adapter integration — sink resolution, decryption, delivery, stamping."""

from __future__ import annotations

import uuid

import pytest

from components.integrations.application.ports.alert_sink_port import AlertMessage, SlackSink
from components.integrations.application.providers.secret_envelope_provider import encrypt_secret
from components.integrations.infrastructure.adapters import slack_alert_adapter as mod
from components.integrations.infrastructure.adapters.slack_alert_adapter import SlackAlertAdapter

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class _Resp:
    def __init__(self, *, ok=True, status=200, error=None):
        self._body = {"ok": True} if ok else {"ok": False, "error": error or "channel_not_found"}
        self.status_code = status
        self.content = b"{}"

    def json(self):
        return self._body


def _make_sink(ws, *, kind="slack", enabled=True, token="xoxb-secret", channel="#soc", min_severity="high"):
    from infrastructure.persistence.integrations.models import SinkConnector

    return SinkConnector.objects.create(
        workspace=ws,
        kind=kind,
        name="soc-slack",
        config={"channel": channel, "min_severity": min_severity},
        secret_ciphertext=encrypt_secret(token) if token else "",
        is_enabled=enabled,
    )


class TestEnabledSlackSinks:
    def test_resolves_and_decrypts(self, workspace_factory):
        ws = workspace_factory()
        _make_sink(ws, token="xoxb-abc", channel="#alerts", min_severity="critical")
        sinks = SlackAlertAdapter().enabled_slack_sinks(ws.id)
        assert len(sinks) == 1
        assert sinks[0].token == "xoxb-abc"
        assert sinks[0].channel == "#alerts"
        assert sinks[0].min_severity == "critical"

    def test_excludes_disabled_and_non_slack_and_tokenless(self, workspace_factory):
        ws = workspace_factory()
        _make_sink(ws, enabled=False)
        _make_sink(ws, kind="webhook")
        _make_sink(ws, token="")
        assert SlackAlertAdapter().enabled_slack_sinks(ws.id) == []

    def test_defaults_min_severity_when_absent(self, workspace_factory):
        ws = workspace_factory()
        from infrastructure.persistence.integrations.models import SinkConnector

        SinkConnector.objects.create(
            workspace=ws,
            kind="slack",
            name="s",
            config={"channel": "#c"},
            secret_ciphertext=encrypt_secret("xoxb-x"),
            is_enabled=True,
        )
        assert SlackAlertAdapter().enabled_slack_sinks(ws.id)[0].min_severity == "high"


class TestDeliver:
    def _sink(self):
        return SlackSink(id=uuid.uuid4(), channel="#soc", min_severity="high", token="xoxb-t")

    def _msg(self):
        return AlertMessage(title="🚨 Critical finding", text="Asset: x", severity="critical")

    def test_success_posts_and_stamps(self, workspace_factory, monkeypatch):
        ws = workspace_factory()
        row = _make_sink(ws)
        captured = {}

        def _fake_post(url, headers=None, json=None, timeout=None):
            captured.update(url=url, headers=headers, json=json)
            return _Resp(ok=True)

        monkeypatch.setattr(mod.requests, "post", _fake_post)
        sink = SlackSink(id=row.id, channel="#soc", min_severity="high", token="xoxb-t")
        assert SlackAlertAdapter().deliver(sink, self._msg()) is True

        assert captured["url"].endswith("/chat.postMessage")
        assert captured["headers"]["Authorization"] == "Bearer xoxb-t"
        assert captured["json"]["channel"] == "#soc"
        row.refresh_from_db()
        assert row.last_delivery_at is not None
        assert row.last_error == ""

    def test_slack_error_stamps_last_error(self, workspace_factory, monkeypatch):
        ws = workspace_factory()
        row = _make_sink(ws)
        monkeypatch.setattr(mod.requests, "post", lambda *a, **k: _Resp(ok=False, error="channel_not_found"))
        sink = SlackSink(id=row.id, channel="#soc", min_severity="high", token="xoxb-t")
        assert SlackAlertAdapter().deliver(sink, self._msg()) is False
        row.refresh_from_db()
        assert "channel_not_found" in row.last_error

    def test_network_error_is_swallowed_and_stamped(self, workspace_factory, monkeypatch):
        ws = workspace_factory()
        row = _make_sink(ws)

        def _boom(*a, **k):
            raise mod.requests.RequestException("timeout")

        monkeypatch.setattr(mod.requests, "post", _boom)
        sink = SlackSink(id=row.id, channel="#soc", min_severity="high", token="xoxb-t")
        assert SlackAlertAdapter().deliver(sink, self._msg()) is False
        row.refresh_from_db()
        assert row.last_error != ""
