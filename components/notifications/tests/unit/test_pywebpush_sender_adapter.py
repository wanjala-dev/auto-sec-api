"""Unit tests for the pywebpush sender adapter's error mapping (T1-S6).

The SDK boundary is stubbed (testing skill §0: stub HTTP/SDK boundaries) —
``pywebpush.webpush`` is replaced with a recording fake; the REAL
``WebPushException`` type is used so the except-clause under test is the
production one. No network, no DB.
"""

from __future__ import annotations

import pytest
import requests
from pywebpush import WebPushException

from components.notifications.application.ports.web_push_sender_port import (
    SubscriptionGoneError,
    TransientPushError,
)
from components.notifications.infrastructure.adapters.pywebpush_web_push_sender_adapter import (
    PywebpushWebPushSenderAdapter,
)

pytestmark = pytest.mark.unit

SUBSCRIPTION_INFO = {
    "endpoint": "https://push.example.com/send/device-1",
    "keys": {"p256dh": "BPubKey", "auth": "authsecret"},
}


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def _raise_webpush(status_code):
    def _fake(**kwargs):
        raise WebPushException(f"Push failed: {status_code}", response=_FakeResponse(status_code))

    return _fake


@pytest.fixture
def vapid_settings(settings):
    settings.WEBPUSH_VAPID_PRIVATE_KEY = "test-private-key"
    settings.WEBPUSH_VAPID_ADMIN_EMAIL = "ops@example.org"
    return settings


class TestSuccessPath:
    def test_passes_subscription_payload_ttl_and_vapid_material(self, monkeypatch, vapid_settings):
        calls = []
        monkeypatch.setattr("pywebpush.webpush", lambda **kwargs: calls.append(kwargs))

        PywebpushWebPushSenderAdapter().send(
            subscription_info=SUBSCRIPTION_INFO,
            payload='{"title": "t"}',
            ttl=86400,
        )

        assert len(calls) == 1
        call = calls[0]
        assert call["subscription_info"] == SUBSCRIPTION_INFO
        assert call["data"] == '{"title": "t"}'
        assert call["ttl"] == 86400
        assert call["vapid_private_key"] == "test-private-key"
        assert call["vapid_claims"] == {"sub": "mailto:ops@example.org"}


class TestErrorMapping:
    @pytest.mark.parametrize("status_code", [404, 410])
    def test_gone_status_maps_to_subscription_gone(self, monkeypatch, vapid_settings, status_code):
        monkeypatch.setattr("pywebpush.webpush", _raise_webpush(status_code))
        with pytest.raises(SubscriptionGoneError):
            PywebpushWebPushSenderAdapter().send(subscription_info=SUBSCRIPTION_INFO, payload="{}", ttl=60)

    @pytest.mark.parametrize("status_code", [400, 401, 413, 429, 500, 502])
    def test_other_statuses_map_to_transient(self, monkeypatch, vapid_settings, status_code):
        monkeypatch.setattr("pywebpush.webpush", _raise_webpush(status_code))
        with pytest.raises(TransientPushError):
            PywebpushWebPushSenderAdapter().send(subscription_info=SUBSCRIPTION_INFO, payload="{}", ttl=60)

    def test_webpush_exception_without_response_is_transient(self, monkeypatch, vapid_settings):
        def _fake(**kwargs):
            raise WebPushException("vapid material malformed")

        monkeypatch.setattr("pywebpush.webpush", _fake)
        with pytest.raises(TransientPushError):
            PywebpushWebPushSenderAdapter().send(subscription_info=SUBSCRIPTION_INFO, payload="{}", ttl=60)

    def test_network_error_is_transient(self, monkeypatch, vapid_settings):
        def _fake(**kwargs):
            raise requests.ConnectionError("connection refused")

        monkeypatch.setattr("pywebpush.webpush", _fake)
        with pytest.raises(TransientPushError):
            PywebpushWebPushSenderAdapter().send(subscription_info=SUBSCRIPTION_INFO, payload="{}", ttl=60)

    def test_gone_error_chains_original_exception(self, monkeypatch, vapid_settings):
        monkeypatch.setattr("pywebpush.webpush", _raise_webpush(410))
        with pytest.raises(SubscriptionGoneError) as excinfo:
            PywebpushWebPushSenderAdapter().send(subscription_info=SUBSCRIPTION_INFO, payload="{}", ttl=60)
        assert isinstance(excinfo.value.__cause__, WebPushException)
