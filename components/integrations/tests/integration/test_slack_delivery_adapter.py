"""Slack delivery adapter — both auth modes, plus the failure translations (ADR 0016 D3/D7)."""

from __future__ import annotations

import uuid

import pytest

from components.integrations.application.ports.delivery_channel_port import (
    DeliveryMessage,
    ResolvedDeliveryConnection,
)
from components.integrations.infrastructure.adapters import slack_delivery_adapter as mod
from components.integrations.infrastructure.adapters.slack_delivery_adapter import (
    SlackDeliveryAdapter,
    is_slack_webhook_url,
)

pytestmark = pytest.mark.integration

_WEBHOOK_URL = "https://hooks.slack.com/services/T000/B000/abcdefghijklmnop"


class _Resp:
    """Stands in for a requests.Response — includes headers, which the old fake lacked."""

    def __init__(self, *, payload=None, status_code=200, content=b"{}", headers=None):
        self._payload = payload if payload is not None else {"ok": True}
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self._payload is _INVALID_JSON:
            raise ValueError("no json")
        return self._payload


_INVALID_JSON = object()


def _bot_connection(**overrides) -> ResolvedDeliveryConnection:
    defaults = dict(
        id=uuid.uuid4(),
        kind="slack",
        auth_mode="bot_token",
        secret="xoxb-token",
        channel="#soc",
        min_severity="high",
    )
    defaults.update(overrides)
    return ResolvedDeliveryConnection(**defaults)


def _webhook_connection(**overrides) -> ResolvedDeliveryConnection:
    defaults = dict(
        id=uuid.uuid4(),
        kind="slack",
        auth_mode="webhook_url",
        secret=_WEBHOOK_URL,
        min_severity="high",
    )
    defaults.update(overrides)
    return ResolvedDeliveryConnection(**defaults)


def _message() -> DeliveryMessage:
    return DeliveryMessage(
        title="🚨 Critical finding",
        body="Asset: `arn:aws:s3:::bucket`",
        severity="critical",
        link="https://app.example.com/findings/1",
    )


class TestWebhookUrlAllowlist:
    @pytest.mark.parametrize(
        "url",
        [
            "https://hooks.slack.com/services/T/B/xyz",
            "https://hooks.slack.com/services/T000/B000/abcdefghijklmnop",
        ],
    )
    def test_accepts_real_slack_webhooks(self, url):
        assert is_slack_webhook_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "http://hooks.slack.com/services/T/B/xyz",  # not https
            "https://hooks.slack.com.evil.test/services/T/B/xyz",  # suffix attack
            "https://evil.test/services/T/B/xyz",  # wrong host
            "https://hooks.slack.com/webhook/T/B/xyz",  # wrong path
            "https://hooks.slack.com/services/",  # no token
            "",
            "not a url",
        ],
    )
    def test_rejects_everything_else(self, url):
        assert is_slack_webhook_url(url) is False


class TestDeliver:
    def test_bot_token_posts_to_web_api_with_bearer(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured.update(url=url, **kwargs)
            return _Resp()

        monkeypatch.setattr(mod.requests, "post", fake_post)
        result = SlackDeliveryAdapter().deliver(_bot_connection(), _message())

        assert result.ok is True
        assert captured["url"] == mod._SLACK_POST_MESSAGE_URL
        assert captured["headers"]["Authorization"] == "Bearer xoxb-token"
        assert captured["json"]["channel"] == "#soc"
        assert captured["allow_redirects"] is False

    def test_webhook_posts_to_the_stored_url_without_auth_header(self, monkeypatch):
        captured = {}

        def fake_post(url, **kwargs):
            captured.update(url=url, **kwargs)
            return _Resp(payload=_INVALID_JSON, content=b"ok")

        monkeypatch.setattr(mod.requests, "post", fake_post)
        result = SlackDeliveryAdapter().deliver(_webhook_connection(), _message())

        assert result.ok is True, "a webhook replies with the plain body 'ok', not JSON"
        assert captured["url"] == _WEBHOOK_URL
        assert captured["headers"] == {}

    def test_renders_block_kit_with_a_link_button(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(mod.requests, "post", lambda url, **kw: captured.update(kw) or _Resp())

        SlackDeliveryAdapter().deliver(_bot_connection(), _message())

        blocks = captured["json"]["blocks"]
        assert blocks[0]["type"] == "header"
        assert any(b.get("type") == "actions" for b in blocks), "the deep link must be actionable"

    def test_refuses_to_post_a_non_slack_webhook_url(self, monkeypatch):
        def explode(*_args, **_kwargs):  # pragma: no cover - must never run
            raise AssertionError("no request may be made for a rejected URL")

        monkeypatch.setattr(mod.requests, "post", explode)
        result = SlackDeliveryAdapter().deliver(
            _webhook_connection(secret="https://evil.test/services/a/b/c"), _message()
        )

        assert result.ok is False
        assert result.permanent is True

    def test_surfaces_retry_after_on_429(self, monkeypatch):
        monkeypatch.setattr(
            mod.requests,
            "post",
            lambda url, **kw: _Resp(status_code=429, headers={"Retry-After": "30"}),
        )
        result = SlackDeliveryAdapter().deliver(_bot_connection(), _message())

        assert result.ok is False
        assert result.retry_after_seconds == 30
        assert result.permanent is False, "rate limiting is transient — it must be retried"

    def test_revoked_credential_is_permanent(self, monkeypatch):
        monkeypatch.setattr(
            mod.requests, "post", lambda url, **kw: _Resp(payload={"ok": False, "error": "invalid_auth"})
        )
        result = SlackDeliveryAdapter().deliver(_bot_connection(), _message())

        assert result.ok is False
        assert result.permanent is True, "retrying a revoked token can never succeed"

    def test_transport_error_is_transient_not_permanent(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise mod.requests.RequestException("connection reset")

        monkeypatch.setattr(mod.requests, "post", boom)
        result = SlackDeliveryAdapter().deliver(_bot_connection(), _message())

        assert result.ok is False
        assert result.permanent is False


class TestVerify:
    def test_bot_token_uses_auth_test_and_sends_nothing(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(mod.requests, "post", lambda url, **kw: captured.update(url=url) or _Resp())

        health = SlackDeliveryAdapter().verify(_bot_connection())

        assert health.ok is True
        assert captured["url"] == mod._SLACK_AUTH_TEST_URL, "auth.test is side-effect free — prefer it"

    def test_webhook_verification_sends_a_real_test_message(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            mod.requests,
            "post",
            lambda url, **kw: captured.update(url=url, json=kw.get("json")) or _Resp(
                payload=_INVALID_JSON, content=b"ok"
            ),
        )

        health = SlackDeliveryAdapter().verify(_webhook_connection())

        assert health.ok is True
        assert captured["url"] == _WEBHOOK_URL
        assert mod._VERIFY_TITLE in captured["json"]["text"]

    def test_failure_detail_never_contains_the_secret(self, monkeypatch):
        monkeypatch.setattr(
            mod.requests, "post", lambda url, **kw: _Resp(payload={"ok": False, "error": "invalid_auth"})
        )
        health = SlackDeliveryAdapter().verify(_bot_connection(secret="xoxb-super-secret"))

        assert health.ok is False
        assert "xoxb-super-secret" not in health.detail
