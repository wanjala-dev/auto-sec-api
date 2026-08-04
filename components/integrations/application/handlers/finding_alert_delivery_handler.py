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


def _frontend_base_url() -> str:
    """The frontend base for HUD deep links, or "" when none is configured.

    Read via the ``SettingsPort`` adapter (locally imported) — the application layer
    never imports ``django.conf`` (same pattern as content's newsletter links).
    ``FRONTEND_URL`` is the SSOT; ``LOCALHOST_FRONTEND_URL`` is the legacy fallback.
    """
    from components.shared_kernel.infrastructure.adapters.django_settings_adapter import (
        DjangoSettingsAdapter,
    )

    adapter = DjangoSettingsAdapter()
    base = adapter.get("FRONTEND_URL", "") or adapter.get("LOCALHOST_FRONTEND_URL", "")
    return str(base or "").rstrip("/")


def _finding_deep_link(event: FindingRaised) -> str:
    """Absolute HUD deep link that opens the FINDINGS panel on this finding.

    Matches the frontend route: ``/ai/v2/<workspace>?panel=findings&finding=<id>``
    (CommandCenterV2's ``?panel=`` deep-link mechanism). "" when no base is set —
    the adapter then simply renders no link.
    """
    base = _frontend_base_url()
    if not base:
        return ""
    return f"{base}/ai/v2/{event.workspace_id}?panel=findings&finding={event.finding_id}"


def _message_body(event: FindingRaised) -> str:
    """Notification-grade summary lines only (ADR 0016 D6) — never the raw payload.

    The vulnerability id + package (when the source carries them) keep lookalike
    titles distinguishable — two "CVE-… in openssl" alerts from different images
    read identically without them.
    """
    lines = []
    if event.vulnerability_id:
        vuln = event.vulnerability_id
        if event.package:
            vuln = f"{vuln} · Package: {event.package}"
        lines.append(f"Vulnerability: {vuln}")
    lines.append(f"Asset: `{event.asset_urn}`")
    lines.append(f"Source: {event.source}")
    lines.append(f"Status: {event.status}")
    return "\n".join(lines)


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
        body=_message_body(event),
        severity=event.severity,
        # Deep link into the HUD on THIS finding — the Slack adapter renders it as
        # the "View in Auto-Sec" button and appends it to the plain-text fallback.
        link=_finding_deep_link(event),
    )

    delivered = 0
    for connection in connections:
        if not severity_meets_threshold(event.severity, connection.min_severity):
            continue
        try:
            adapter = provider.get(connection.kind)
        except UnsupportedDeliveryChannelError:
            logger.warning("delivery_channel_unsupported connection_id=%s kind=%s", connection.id, connection.kind)
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
