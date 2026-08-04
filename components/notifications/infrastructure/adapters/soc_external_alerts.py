"""Workspace-level SOC alert dispatch — the producer side of the external funnel.

ADR 0016 P1 (#246) built the funnel's external leg: ``NotificationDispatcher.
dispatch()`` → ``_enqueue_external_leg`` → ``external_event_policy`` →
``deliver_external`` — and retired the direct ``FindingRaised → Slack`` handler.
The policy is fail-closed on ``metadata["kind"]``, so nothing reaches a
customer's channel until a producer consciously dispatches one of the mapped
kinds. This module is that producer side: the application-layer event handlers
(``application/handlers/*_alert_handler.py``) subscribe to the shared-kernel
events and delegate here, where the Django-facing work (workspace/owner
resolution, the dispatcher call) lives.

Every dispatch goes through the ONE sanctioned funnel entry —
``NotificationDispatcher.dispatch()`` (enforced by
``tests/architecture/test_notification_dispatch_rules.py``) — with
``recipients=()``: these are workspace-level external alerts (a Slack channel is
a team destination), and their in-app counterparts already exist on their own
paths (the board-card bridge notifies the owner per AI finding card; scans
surface in the HUD via the background-job reporter). Dispatching per-user rows
here too would double-notify.

Loss-tolerant: an alert dispatch failure is logged and never breaks the event
handler that triggered it — same posture as ``soc_notification_signal_bridge``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The HUD deep-link contract shipped by #247: the frontend reads
# ``?panel=findings&finding=<id>`` and opens the finding via the detail endpoint.
_FINDING_DEEP_LINK = "/ai/v2/{workspace_id}?panel=findings&finding={finding_id}"


def _dispatch_workspace_event(workspace_id, *, verb: str, notification_type: str, metadata: dict) -> None:
    """Fire ONE workspace-level dispatch through the canonical funnel.

    The funnel's external leg fires before the per-recipient fan-out, so
    ``recipients=()`` yields exactly the workspace-level external delivery and
    nothing else. The workspace owner stands in as the actor (system-event
    convention — same as the kill-switch bridge); with no recipients the actor
    is only ever used as an id.
    """
    from django.apps import apps

    from components.notifications.infrastructure.adapters.notification_service import (
        NotificationDispatcher,
    )

    try:
        Workspace = apps.get_model("workspaces", "Workspace")
        workspace = Workspace.objects.filter(pk=workspace_id).first()
        if workspace is None:
            logger.warning("soc_external_alert_workspace_missing workspace_id=%s", workspace_id)
            return
        owner = getattr(workspace, "workspace_owner", None)
        if owner is None:
            logger.warning("soc_external_alert_owner_missing workspace_id=%s", workspace_id)
            return

        NotificationDispatcher().dispatch(
            actor=owner,
            workspace=workspace,
            verb=verb,
            notification_type=notification_type,
            recipients=(),
            metadata=metadata,
            allow_self_notify=True,
        )
    except Exception:
        logger.exception(
            "soc_external_alert_dispatch_failed workspace_id=%s kind=%s",
            workspace_id,
            metadata.get("kind"),
        )


def dispatch_finding_filed(event) -> None:
    """``FindingRaised`` (new + critical) → one ``soc.finding_filed`` dispatch.

    The producer gates on ``is_new`` + critical (the anti-flood line: criticals
    alert individually, everything else rides the per-scan digest — ADR 0016
    D5); the leg's per-connection severity floor + KEV bypass then apply to the
    metadata. The verb carries the vulnerability identity (#247) so lookalike
    CVE titles stay distinguishable in a chat channel.
    """
    verb = (event.title or "").strip() or "a new finding"
    if event.vulnerability_id and event.package:
        verb = f"{verb} — {event.vulnerability_id} in {event.package}"
    elif event.vulnerability_id:
        verb = f"{verb} — {event.vulnerability_id}"

    metadata = {
        "kind": "soc.finding_filed",
        "finding_id": str(event.finding_id),
        "severity": event.severity,
        "asset_urn": event.asset_urn,
        "source": event.source,
        "is_new": bool(event.is_new),
        "deep_link": _FINDING_DEEP_LINK.format(workspace_id=event.workspace_id, finding_id=event.finding_id),
    }
    if event.vulnerability_id:
        metadata["vulnerability_id"] = event.vulnerability_id
    if event.package:
        metadata["package"] = event.package

    _dispatch_workspace_event(
        event.workspace_id,
        verb=verb,
        notification_type="ai_event",
        metadata=metadata,
    )


def dispatch_scan_completed(event) -> None:
    """``ScanCompleted`` → the ONE-per-scan ``soc.scan_completed`` digest.

    ``scan_id`` is the dedup identity (a redelivered digest converges in the
    ledger); zero severity counts are omitted so a clean scan renders as
    "No new findings." rather than a row of zeros.
    """
    engine = event.engine or event.source
    metadata = {
        "kind": "soc.scan_completed",
        "scan_id": str(event.scan_id or event.event_id),
        "engine": engine,
        "source": event.source,
    }
    if event.account_id:
        metadata["account_id"] = event.account_id
    if event.target_ref:
        metadata["target"] = event.target_ref
    for level in ("critical", "high", "medium", "low"):
        count = int(getattr(event, level, 0) or 0)
        if count:
            metadata[level] = count
    observed = int(event.findings_observed or 0)
    if observed:
        metadata["total"] = observed

    target = event.target_ref or event.account_id
    verb = f"completed a {engine} scan" + (f" of {target}" if target else "")
    _dispatch_workspace_event(
        event.workspace_id,
        verb=verb,
        notification_type="system",
        metadata=metadata,
    )


def dispatch_scan_failed(event) -> None:
    """``ScanFailed`` → ``soc.scan_failed`` — coverage is degraded, say so.

    ``run_id`` is a per-attempt identity so a recurring nightly failure alerts
    every night instead of silently deduping against the first one.
    """
    engine = event.engine or event.source
    metadata = {
        "kind": "soc.scan_failed",
        "run_id": str(event.run_id or event.event_id),
        "engine": engine,
        "source": event.source,
        "reason": event.reason or "scan engine failure",
    }
    if event.account_id:
        metadata["account_id"] = event.account_id
    if event.target_ref:
        metadata["target"] = event.target_ref

    target = event.target_ref or event.account_id
    verb = f"{engine} scan failed" + (f" for {target}" if target else "")
    _dispatch_workspace_event(
        event.workspace_id,
        verb=verb,
        notification_type="system",
        metadata=metadata,
    )
