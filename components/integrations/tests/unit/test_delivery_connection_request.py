"""Edge validation for delivery-connection CRUD (ADR 0016 D2).

A connection that cannot deliver must be rejected at create time — the alternative
is discovering it when an alert silently fails to arrive during an incident.
"""

from __future__ import annotations

import pytest

from components.integrations.api.requests.delivery_connection_request import (
    CreateDeliveryConnectionRequest,
    UpdateDeliveryConnectionRequest,
)
from components.shared_kernel.domain.delivery_events import DEFAULT_EXTERNAL_EVENT_KEYS

pytestmark = pytest.mark.unit

_WEBHOOK = "https://hooks.slack.com/services/T000/B000/abcdefghijklmnop"


def _payload(**overrides) -> dict:
    base = {"kind": "slack", "name": "Sec alerts", "auth_mode": "webhook_url", "secret": _WEBHOOK}
    base.update(overrides)
    return base


class TestCreate:
    def test_accepts_a_valid_webhook_connection(self):
        req = CreateDeliveryConnectionRequest.from_payload(_payload())
        assert req.validation_error() is None
        assert req.events == DEFAULT_EXTERNAL_EVENT_KEYS

    def test_rejects_a_non_slack_webhook_url(self):
        req = CreateDeliveryConnectionRequest.from_payload(_payload(secret="https://evil.test/services/a/b/c"))
        assert "hooks.slack.com" in (req.validation_error() or "")

    def test_rejects_a_kind_without_a_shipped_adapter(self):
        """``webhook`` is a declared kind with no adapter yet — accepting it would
        create a row that can never deliver."""
        req = CreateDeliveryConnectionRequest.from_payload(_payload(kind="webhook"))
        assert "not available yet" in (req.validation_error() or "")

    def test_rejects_an_unknown_kind(self):
        req = CreateDeliveryConnectionRequest.from_payload(_payload(kind="carrier-pigeon"))
        assert "Unknown channel kind" in (req.validation_error() or "")

    def test_requires_a_name(self):
        req = CreateDeliveryConnectionRequest.from_payload(_payload(name="   "))
        assert req.validation_error() == "A name is required."

    def test_requires_a_secret(self):
        req = CreateDeliveryConnectionRequest.from_payload(_payload(secret=""))
        assert "webhook URL is required" in (req.validation_error() or "")

    def test_bot_token_requires_a_channel(self):
        """A webhook carries its channel in the URL; a bot token does not, so without
        one the message has nowhere to land."""
        req = CreateDeliveryConnectionRequest.from_payload(
            _payload(auth_mode="bot_token", secret="xoxb-token", channel="")
        )
        assert "channel is required" in (req.validation_error() or "")

    def test_bot_token_with_a_channel_is_accepted(self):
        req = CreateDeliveryConnectionRequest.from_payload(
            _payload(auth_mode="bot_token", secret="xoxb-token", channel="#soc")
        )
        assert req.validation_error() is None

    def test_rejects_an_unknown_severity_floor(self):
        """An operator who typed 'urgent' gets an error, not silent reinterpretation."""
        req = CreateDeliveryConnectionRequest.from_payload(_payload(min_severity="urgent"))
        assert "Unknown severity" in (req.validation_error() or "")

    def test_rejects_unknown_event_keys(self):
        req = CreateDeliveryConnectionRequest.from_payload(_payload(events=["draft_pr_opened", "made_up"]))
        assert "made_up" in (req.validation_error() or "")

    def test_rejects_events_that_are_not_a_list(self):
        req = CreateDeliveryConnectionRequest.from_payload(_payload(events="draft_pr_opened"))
        assert "must be a list" in (req.validation_error() or "")

    def test_an_empty_event_list_is_allowed(self):
        """Unticking everything is an explicit choice — silence, not a reset to defaults."""
        req = CreateDeliveryConnectionRequest.from_payload(_payload(events=[]))
        assert req.validation_error() is None
        assert req.events == ()


class TestUpdate:
    def test_omitted_fields_are_none_so_nothing_is_touched(self):
        req = UpdateDeliveryConnectionRequest.from_payload({"name": "Renamed"})
        assert req.name == "Renamed"
        assert req.secret is None
        assert req.events is None
        assert req.validation_error() is None

    def test_rotating_to_a_bad_url_is_rejected(self):
        req = UpdateDeliveryConnectionRequest.from_payload({"secret": "https://evil.test/x"})
        assert "hooks.slack.com" in (req.validation_error() or "")

    def test_error_status_cannot_be_set_by_hand(self):
        """``error`` is system-owned — only verify/delivery may set it, or an operator
        could mark a broken channel healthy."""
        req = UpdateDeliveryConnectionRequest.from_payload({"status": "error"})
        assert "Status must be one of" in (req.validation_error() or "")

    def test_disabling_is_allowed(self):
        req = UpdateDeliveryConnectionRequest.from_payload({"is_enabled": False, "status": "disabled"})
        assert req.validation_error() is None
        assert req.is_enabled is False
