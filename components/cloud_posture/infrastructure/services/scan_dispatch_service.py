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

# How long a deferred account is told to wait before the next sweep should look
# at it again. Roughly the time a Prowler scan of one account takes, so the
# ceiling has actually drained by the time the next wave arrives. Far below the
# per-account cooldown, so a drain wave can only reach accounts that have NOT
# been scanned this cycle — it never turns a nightly scan into a rolling one.
DEFER_RETRY_AFTER_SECONDS = int(os.environ.get("CLOUD_POSTURE_DEFER_RETRY_AFTER_SECONDS", "300"))


def _max_concurrent_scans() -> int:
    """The configured global ceiling; ``<= 0`` means unbounded.

    Read per call rather than at import so an operator changing the env (or a
    test overriding the setting) takes effect without a redeploy of intent.
    """
    from django.conf import settings

    try:
        return int(getattr(settings, "CLOUD_POSTURE_MAX_CONCURRENT_SCANS", 0) or 0)
    except (TypeError, ValueError):
        logger.warning("CLOUD_POSTURE_MAX_CONCURRENT_SCANS is not an integer; treating the cap as unbounded")
        return 0


def _headroom() -> int | None:
    """Slots available under the global ceiling, or ``None`` when unbounded."""
    from components.scanning.application.providers.scan_gate_provider import count_in_flight

    cap = _max_concurrent_scans()
    if cap <= 0:
        return None
    return max(0, cap - count_in_flight(SOURCE))


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

    Shared by the beat scheduler, the on-demand endpoint and the post-verify
    auto-scan (byte-for-byte the same path — only ``trigger``/``triggered_by``
    differ). Skips terminal links (FAILED / SUSPENDED / EXCLUDED); DISCOVERED +
    VERIFIED are scanned — the scan re-verifies each account on every run.

    **Bounded by the global in-flight ceiling** (``CLOUD_POSTURE_MAX_CONCURRENT_SCANS``).
    Accounts past the ceiling are DEFERRED, not dropped: they take no dispatch
    lock, start no cooldown, and are dispatched by the next sweep — which is why
    the return distinguishes ``deferred`` from ``blocked``. Reporting them as
    "blocked" would be the silent-failure class this gate exists to remove: an
    operator would read "40 of 200 scanned" as a mystery rather than as a queue.

    Returns ``{"scannable", "enqueued", "blocked", "deferred", "retry_after"}``
    where ``enqueued + blocked + deferred == scannable`` — every account lands in
    exactly one bucket, so nothing can go missing unnoticed.
    """
    from infrastructure.persistence.integrations.models import AwsAccountLink

    terminal = [
        AwsAccountLink.Status.FAILED,
        AwsAccountLink.Status.SUSPENDED,
        AwsAccountLink.Status.EXCLUDED,
    ]
    account_ids = list(
        AwsAccountLink.objects.filter(connection_id=connection.id)
        .exclude(status__in=terminal)
        .values_list("account_id", flat=True)
    )

    # Counted ONCE, then decremented locally: the ScanRun rows for this sweep's
    # own dispatches do not exist yet at the moment we ask, so re-reading the
    # count per account would let a single fan-out blow straight through the
    # ceiling it just measured.
    headroom = _headroom()

    enqueued = 0
    blocked = 0
    deferred = 0
    retry_after: int | None = None
    for account_id in account_ids:
        if headroom is not None and headroom <= 0:
            deferred += 1
            retry_after = max(retry_after or 0, DEFER_RETRY_AFTER_SECONDS)
            continue
        verdict = dispatch_account_scan(connection, account_id, trigger=trigger, triggered_by=triggered_by)
        if verdict["enqueued"]:
            enqueued += 1
            if headroom is not None:
                headroom -= 1
        else:
            blocked += 1
            if verdict["retry_after"] is not None:
                retry_after = max(retry_after or 0, verdict["retry_after"])

    if deferred:
        logger.info(
            "cloud_posture_scans_deferred workspace_id=%s connection_id=%s cap=%s "
            "scannable=%d enqueued=%d deferred=%d retry_after=%s",
            connection.workspace_id,
            connection.id,
            _max_concurrent_scans(),
            len(account_ids),
            enqueued,
            deferred,
            retry_after,
        )

    return {
        "scannable": len(account_ids),
        "enqueued": enqueued,
        "blocked": blocked,
        "deferred": deferred,
        "retry_after": retry_after,
    }


def dispatch_scans_for_workspace_connection(
    *, workspace_id, connection_id, trigger: str = "manual", triggered_by=None
) -> dict | None:
    """Workspace-scoped entry for the on-demand endpoint and the post-verify auto-scan.

    Returns the dispatch counts (``scannable`` / ``enqueued`` / ``blocked`` /
    ``deferred`` / ``retry_after``), or ``None`` when no such connection belongs
    to the workspace (the endpoint maps that to 404).
    """
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    connection = AwsOrganizationConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()
    if connection is None:
        return None
    return dispatch_connection_scans(connection, trigger=trigger, triggered_by=triggered_by)
