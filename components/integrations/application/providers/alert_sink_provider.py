"""Composition root for the alert-sink port."""

from __future__ import annotations

from components.integrations.application.ports.alert_sink_port import AlertSinkPort

_adapter: AlertSinkPort | None = None


def get_alert_sink_port() -> AlertSinkPort:
    global _adapter
    if _adapter is None:
        from components.integrations.infrastructure.adapters.slack_alert_adapter import (
            SlackAlertAdapter,
        )

        _adapter = SlackAlertAdapter()
    return _adapter
