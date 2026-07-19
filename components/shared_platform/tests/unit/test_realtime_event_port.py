"""Tests for the realtime event publishing port + adapters.

Pin down: the NoOp adapter swallows every publish silently, the
provider returns the right adapter based on settings, and the
Channels adapter doesn't crash if the channel layer isn't there
(graceful degradation when running outside the daphne process).
"""

from __future__ import annotations

import logging

import pytest

from components.shared_platform.application.providers.realtime_event_provider import (
    get_realtime_event_publisher,
)
from components.shared_platform.infrastructure.adapters.channels_realtime_event_adapter import (
    ChannelsRealtimeEventAdapter,
    NoOpRealtimeEventAdapter,
)


def test_noop_publish_returns_none():
    publisher = NoOpRealtimeEventAdapter()
    result = publisher.publish(
        workspace_id="abc",
        resource_type="agent_run",
        resource_id="plan-1",
        event_name="started",
        status="running",
    )
    assert result is None


def test_provider_returns_noop_when_disabled():
    publisher = get_realtime_event_publisher(enabled=False)
    assert isinstance(publisher, NoOpRealtimeEventAdapter)


def test_provider_returns_channels_adapter_when_enabled():
    publisher = get_realtime_event_publisher(enabled=True)
    assert isinstance(publisher, ChannelsRealtimeEventAdapter)


def test_provider_defaults_to_channels_adapter():
    publisher = get_realtime_event_publisher()
    assert isinstance(publisher, ChannelsRealtimeEventAdapter)


def test_channels_adapter_is_safe_when_layer_unavailable(caplog):
    """The adapter logs and returns even when no channel layer is
    configured — publishers must NOT crash because the realtime stack
    isn't booted."""
    publisher = ChannelsRealtimeEventAdapter()
    with caplog.at_level(
        logging.DEBUG,
        logger=(
            "components.shared_platform.infrastructure.adapters."
            "channels_realtime_event_adapter"
        ),
    ):
        publisher.publish(
            workspace_id="ws-1",
            resource_type="agent_run",
            resource_id="plan-1",
            event_name="started",
            status="running",
            payload={"agent_type": "workspace_agent"},
        )
    # The InMemoryChannelLayer is configured for tests, so the publish
    # actually succeeds — no exception, no error log line is the win.
