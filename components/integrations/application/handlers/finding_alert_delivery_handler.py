"""Deliver findings to a workspace's connected channels (roadmap #5 — outbound delivery).

Subscribes to the shared-kernel ``FindingRaised`` (C1: both emitter and subscriber
depend only on the kernel — integrations never imports findings). Runs async, one
Celery task per handler via ``CeleryEventPublisher``, so a slow/failing delivery is
fault-isolated and retryable and never blocks the finding pipeline.

RETIREMENT NOTICE (ADR 0016 D1): this is the *parallel notifier* the ADR converges
away. It has no preference model, no delivery ledger, no retry, and a per-event
shape that means one scan raising 400 qualifying findings posts 400 messages.
Delivery moves to the notifications funnel's workspace-level external leg, where
those properties are inherited rather than reimplemented. This module is deleted in
that change; it is kept working here only so the port generalization ships on its
own and nothing goes dark in between.
"""

from __future__ import annotations

import logging

from components.integrations.application.ports.delivery_channel_port import DeliveryMessage
from components.integrations.application.providers.delivery_channel_provider import (
    UnsupportedDeliveryChannelError,
    get_delivery_channel_provider,
    get_delivery_connection_repository,
)
from components.integrations.domain.alert_policy import severity_meets_threshold
from components.shared_kernel.application.subscription_registry import subscribes_to
from components.shared_kernel.domain.events import FindingRaised

logger = logging.getLogger(__name__)

_SEVERITY_EMOJI = {"critical": "🚨", "high": "🔴", "medium": "🟠", "low": "🟡", "informational": "⚪"}


@subscribes_to(FindingRaised)
def deliver_finding_to_slack(event: FindingRaised) -> None:
    if not event.is_new:
        # A re-observation of an already-open finding. The event carries ``is_new``
        # precisely so consumers can avoid re-alerting on steady-state noise; with
        # CSPM rescanning nightly and the detector cycle running every five minutes,
        # not reading it turns the channel into a recurring-noise generator.
        return

    repository = get_delivery_connection_repository()
    connections = repository.enabled_for_workspace(event.workspace_id)
    if not connections:
        return

    provider = get_delivery_channel_provider()
    message = DeliveryMessage(
        title=f"{_SEVERITY_EMOJI.get(event.severity, '•')} {event.severity.title()} finding: {event.title}"[:250],
        body=f"Asset: `{event.asset_urn}`\nSource: {event.source}\nStatus: {event.status}",
        severity=event.severity,
    )

    delivered = 0
    for connection in connections:
        if not severity_meets_threshold(event.severity, connection.min_severity):
            continue
        try:
            adapter = provider.get(connection.kind)
        except UnsupportedDeliveryChannelError:
            logger.warning(
                "delivery_channel_unsupported connection_id=%s kind=%s", connection.id, connection.kind
            )
            continue
        result = adapter.deliver(connection, message)
        if result.ok:
            repository.mark_delivered(connection.id)
            delivered += 1
        else:
            repository.mark_error(connection.id, result.detail)

    logger.info(
        "finding_delivery workspace_id=%s finding_id=%s connections=%s delivered=%s severity=%s",
        event.workspace_id,
        event.finding_id,
        len(connections),
        delivered,
        event.severity,
    )
