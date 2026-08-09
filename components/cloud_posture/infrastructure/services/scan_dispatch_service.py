"""Gated dispatch of CSPM scans onto the scanning spine (audit R1).

The pillar's ONE dispatch seam: both the on-demand "Scan now" endpoint and the
beat scheduler fan out per-account scans through here, so both paths get the
same anti-spam gate (``check_and_lock_dispatch`` — one scan per account per
cooldown, never more than one in flight) and the same provenance
(``trigger`` / ``triggered_by`` stamped onto the ``ScanRun`` by the shared
choreography). This replaces the pillar's forked task pipeline — execution,
run lifecycle, failure rows, lock release, SSOT emit, and audit-trail writes
all live in ``components/scanning`` now, exactly like code_security.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

SOURCE = "cloud_posture.prowler"

# One user-visible scan per account per hour by default, matching the
# code_security repo cooldown (Henry, 2026-08-08: budget-gate manual scans so
# users can't spam the system). Env-overridable per deployment.
COOLDOWN_SECONDS = int(os.environ.get("CLOUD_POSTURE_SCAN_COOLDOWN_SECONDS", "3600"))


def dispatch_account_scan(connection, account_id: str, *, trigger: str, triggered_by=None) -> dict:
    """Gate + dispatch ONE per-account scan. Returns the gate verdict:
    ``{"enqueued": bool, "reason": "", "retry_after": int | None}``."""
    from components.scanning.application.providers.scan_dispatch_provider import dispatch_scan
    from components.scanning.application.providers.scan_gate_provider import (
        check_and_lock_dispatch,
        release_dispatch_lock,
    )

    gate = check_and_lock_dispatch(
        workspace_id=str(connection.workspace_id),
        source=SOURCE,
        target_ref=account_id,
        cooldown_seconds=COOLDOWN_SECONDS,
    )
    if not gate["allowed"]:
        logger.info(
            "cloud_posture_scan_gated workspace_id=%s account=%s reason=%s retry_after=%s",
            connection.workspace_id,
            account_id,
            gate["reason"],
            gate["retry_after"],
        )
        return {"enqueued": False, "reason": gate["reason"], "retry_after": gate["retry_after"]}

    try:
        dispatch_scan(
            source=SOURCE,
            workspace_id=str(connection.workspace_id),
            target_ref=account_id,
            connection_id=str(connection.id),
            account_id=account_id,
            trigger=trigger,
            triggered_by=str(triggered_by) if triggered_by else None,
            params={"regions": list(connection.regions or [])},
        )
    except Exception:
        # The enqueue itself failed — free the lock so a retry isn't cooldown-locked.
        release_dispatch_lock(workspace_id=str(connection.workspace_id), source=SOURCE, target_ref=account_id)
        raise
    return {"enqueued": True, "reason": "", "retry_after": None}


def dispatch_connection_scans(connection, *, trigger: str, triggered_by=None) -> dict:
    """Gate + dispatch one scan per scannable account link of a connection.

    Shared by the beat scheduler and the on-demand endpoint (byte-for-byte the
    same path — only ``trigger``/``triggered_by`` differ). Skips terminal links
    (FAILED / SUSPENDED / EXCLUDED); DISCOVERED + VERIFIED are scanned — the
    scan re-verifies each account on every run. Returns
    ``{"enqueued": n, "blocked": m, "retry_after": max-or-None}``.
    """
    from infrastructure.persistence.integrations.models import AwsAccountLink

    terminal = [
        AwsAccountLink.Status.FAILED,
        AwsAccountLink.Status.SUSPENDED,
        AwsAccountLink.Status.EXCLUDED,
    ]
    account_ids = (
        AwsAccountLink.objects.filter(connection_id=connection.id)
        .exclude(status__in=terminal)
        .values_list("account_id", flat=True)
    )

    enqueued = 0
    blocked = 0
    retry_after: int | None = None
    for account_id in account_ids:
        verdict = dispatch_account_scan(connection, account_id, trigger=trigger, triggered_by=triggered_by)
        if verdict["enqueued"]:
            enqueued += 1
        else:
            blocked += 1
            if verdict["retry_after"] is not None:
                retry_after = max(retry_after or 0, verdict["retry_after"])
    return {"enqueued": enqueued, "blocked": blocked, "retry_after": retry_after}


def dispatch_scans_for_workspace_connection(
    *, workspace_id, connection_id, trigger: str = "manual", triggered_by=None
) -> dict | None:
    """Workspace-scoped entry for the on-demand endpoint.

    Returns the dispatch counts, or ``None`` when no such connection belongs to
    the workspace (the endpoint maps that to 404).
    """
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    connection = AwsOrganizationConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()
    if connection is None:
        return None
    return dispatch_connection_scans(connection, trigger=trigger, triggered_by=triggered_by)
