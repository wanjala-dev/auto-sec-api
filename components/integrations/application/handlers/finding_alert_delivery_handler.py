"""Deliver findings to a workspace's Slack sinks (roadmap #5 — outbound delivery).

Subscribes to the shared-kernel ``FindingRaised`` (C1: both emitter and subscriber
depend only on the kernel — integrations never imports findings). Runs async, one
Celery task per handler via ``CeleryEventPublisher``, so a slow/failing Slack call is
fault-isolated and retryable and never blocks the finding pipeline. The sink's
``min_severity`` is the operator's noise dial.
"""

from __future__ import annotations

import logging

from components.integrations.application.ports.alert_sink_port import AlertMessage
from components.integrations.application.providers.alert_sink_provider import get_alert_sink_port
from components.integrations.domain.alert_policy import severity_meets_threshold
from components.shared_kernel.application.subscription_registry import subscribes_to
from components.shared_kernel.domain.events import FindingRaised

logger = logging.getLogger(__name__)

_SEVERITY_EMOJI = {"critical": "🚨", "high": "🔴", "medium": "🟠", "low": "🟡", "informational": "⚪"}


@subscribes_to(FindingRaised)
def deliver_finding_to_slack(event: FindingRaised) -> None:
    port = get_alert_sink_port()
    sinks = port.enabled_slack_sinks(event.workspace_id)
    if not sinks:
        return

    message = AlertMessage(
        title=f"{_SEVERITY_EMOJI.get(event.severity, '•')} {event.severity.title()} finding: {event.title}"[:250],
        text=f"Asset: `{event.asset_urn}`\nSource: {event.source}\nStatus: {event.status}",
        severity=event.severity,
    )

    delivered = 0
    for sink in sinks:
        if not severity_meets_threshold(event.severity, sink.min_severity):
            continue
        if port.deliver(sink, message):
            delivered += 1
    logger.info(
        "finding_slack_delivery workspace_id=%s finding_id=%s sinks=%s delivered=%s severity=%s",
        event.workspace_id,
        event.finding_id,
        len(sinks),
        delivered,
        event.severity,
    )
