"""External delivery task — the workspace-level leg of the funnel (ADR 0016 D5/D6/D7).

The per-user channels (realtime, web push, email) fan out once per recipient. This
one fires ONCE per dispatch, because a Slack channel is a team destination, not N
inboxes — delivering it per recipient would post the same message once for every
member of the workspace.

Outcomes per ledger row (mirrors ``email_tasks``):

    sent        the provider accepted the message
    skipped     channel flag off, event not subscribed, below the severity floor,
                or a re-observation. Terminal, never retried.
    failed      the provider rejected it. A deterministic rejection (revoked
                webhook, bad token) stays failed; a transient one re-raises for
                Celery retry and the retry re-claims the row.

Rate limiting is honoured rather than guessed: a 429 carries ``Retry-After`` and the
retry uses that countdown instead of the exponential backoff.

Messages leave the tenant, so this module logs ids, counts, and event keys only —
never the rendered body, the metadata, or anything from a connection's credential.
"""

from __future__ import annotations

import logging

from celery import shared_task

# Another context's DOMAIN is a legal import (architecture Rule 3); its
# infrastructure is not — connections are resolved through integrations'
# application provider below.
from components.integrations.domain.alert_policy import severity_meets_threshold

logger = logging.getLogger(__name__)

CHANNEL_DISABLED_REASON = "external channel disabled (NOTIF_EXTERNAL_CHANNEL_ENABLED off)"
NOT_SUBSCRIBED_REASON = "connection is not subscribed to this event"
BELOW_FLOOR_REASON = "below the connection's severity floor"
RE_OBSERVATION_REASON = "re-observation of an already-open finding"
NO_ADAPTER_REASON = "no delivery adapter is registered for this channel kind"
ALREADY_HANDLED_REASON = "another worker holds this delivery"

_MAX_ERROR_LENGTH = 500


class TransientExternalDeliveryError(Exception):
    """Raised to hand a provider failure to Celery's retry machinery."""


@shared_task(
    name="notifications.deliver_external",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    soft_time_limit=240,
    time_limit=300,
)
def deliver_external(self, *, workspace_id, event_key, verb="", metadata=None, link=None):
    """Deliver one dispatched event to every subscribed channel in the workspace."""
    from components.integrations.application.providers.delivery_channel_provider import (
        UnsupportedDeliveryChannelError,
        get_delivery_channel_provider,
        get_delivery_connection_repository,
    )
    from components.notifications.domain.policies.external_event_policy import (
        derive_dedup_key,
        is_kev,
        is_new_observation,
    )
    from components.notifications.domain.services.external_message_builder import build_message
    from components.notifications.infrastructure.adapters.external_channel_config import (
        external_delivery_enabled,
    )
    from components.notifications.infrastructure.repositories.external_delivery_repository import (
        ExternalDeliveryRepository,
    )

    metadata = metadata or {}
    ledger = ExternalDeliveryRepository()
    connections = get_delivery_connection_repository().enabled_for_workspace(workspace_id)
    if not connections:
        return {"delivered": 0, "skipped": 0, "connections": 0}

    dedup_key = derive_dedup_key(workspace_id=str(workspace_id), event_key=event_key, metadata=metadata)
    severity = str(metadata.get("severity") or "").strip().lower()
    kev = is_kev(metadata)
    fresh = is_new_observation(metadata)
    channel_on = external_delivery_enabled()
    provider = get_delivery_channel_provider()
    message = build_message(event_key=event_key, verb=verb, metadata=metadata, link=_absolutize(link or ""))

    delivered = skipped = 0
    transient_error: str | None = None
    retry_after: int | None = None

    for connection in connections:
        record = ledger.record(connection_id=connection.id, dedup_key=dedup_key, event_key=event_key)

        reason = _skip_reason(
            channel_on=channel_on,
            connection=connection,
            event_key=event_key,
            severity=severity,
            kev=kev,
            fresh=fresh,
        )
        if reason:
            ledger.mark_skipped(record.id, reason=reason)
            skipped += 1
            continue

        # The DB decides who delivers — a lost claim means a sibling worker holds
        # it, or it already went out. Either way this worker must not post.
        if not ledger.claim(record.id):
            skipped += 1
            continue

        try:
            adapter = provider.get(connection.kind)
        except UnsupportedDeliveryChannelError:
            ledger.mark_skipped(record.id, reason=NO_ADAPTER_REASON)
            skipped += 1
            continue

        result = adapter.deliver(connection, message)
        if result.ok:
            ledger.mark_sent(record.id)
            delivered += 1
            continue

        ledger.mark_failed(record.id, error=result.detail)
        if result.permanent:
            # A revoked webhook or bad token will never succeed — retrying is noise.
            continue
        transient_error = result.detail or "external delivery failed"
        retry_after = result.retry_after_seconds or retry_after

    logger.info(
        "deliver_external workspace_id=%s event=%s connections=%d delivered=%d skipped=%d task_id=%s",
        workspace_id,
        event_key,
        len(connections),
        delivered,
        skipped,
        self.request.id,
    )

    if transient_error:
        exc = TransientExternalDeliveryError(transient_error[:_MAX_ERROR_LENGTH])
        # Honour the provider's own instruction over our backoff curve — Slack
        # tells us exactly how long to wait, and guessing shorter just burns quota.
        if retry_after:
            raise self.retry(exc=exc, countdown=retry_after)
        raise self.retry(exc=exc)

    return {"delivered": delivered, "skipped": skipped, "connections": len(connections)}


def _absolutize(link: str) -> str:
    """Make the funnel's relative deep link absolute at send time.

    The funnel stores RELATIVE paths (``link_resolver``) and each link-consuming
    channel absolutizes when it leaves the product — web push and email already do
    exactly this via ``resolve_frontend_base_url()``. The external leg is such a
    channel: a Slack Block Kit button rejects a non-http URL, so a relative path
    would fail the whole delivery. Best-effort — an unresolvable base degrades to
    the raw path rather than blocking a live security alert.
    """
    if not link.startswith("/") or link.startswith("//"):
        return link
    try:
        from components.shared_platform.application.providers.core_utils_provider import (
            CoreUtilsProvider,
        )

        base = CoreUtilsProvider().resolve_frontend_base_url()
    except Exception:
        logger.exception("deliver_external_frontend_base_resolve_failed")
        return link
    if not base:
        return link
    return f"{base.rstrip('/')}{link}"


def _skip_reason(*, channel_on, connection, event_key, severity, kev, fresh) -> str | None:
    """Every gate in one place, so the reasons recorded on the ledger are exhaustive
    and a operator can always answer "why didn't this reach Slack?"."""
    if not channel_on:
        return CHANNEL_DISABLED_REASON
    if event_key not in (connection.events or ()):
        return NOT_SUBSCRIBED_REASON
    if not fresh:
        return RE_OBSERVATION_REASON
    # KEV bypasses the floor entirely — a known-exploited finding is never noise,
    # whatever the operator set the dial to (ADR 0016 D5).
    if severity and not kev and not severity_meets_threshold(severity, connection.min_severity):
        return BELOW_FLOOR_REASON
    return None
