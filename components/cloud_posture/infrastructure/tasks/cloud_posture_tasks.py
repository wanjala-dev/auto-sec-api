"""Celery orchestration for the Prowler CSPM scan — spine edition (audit R1).

``schedule_prowler_runs`` (beat) fans out one gated ``scanning.run_scan``
dispatch per scannable account of every CONNECTED connection whose workspace
has opted in (``feature.cloud_posture``); the on-demand "Scan now" endpoint
reuses the exact same per-connection dispatch seam
(``scan_dispatch_service.dispatch_connection_scans``), so both paths are
byte-for-byte identical — only ``trigger``/``triggered_by`` differ.

The pillar's forked ~280-line pipeline (own task, own run table writes, no
gate, no triggered-by, no failure rows) is GONE: execution, the ``ScanRun``
lifecycle (honest timestamps, engine version, a FAILED row + error on
failure), the cooldown gate + lock release, the SSOT ``FindingObserved``
emit, and the audit-trail writes all live in the shared ``components/scanning``
choreography now — exactly like container_security and code_security. The
pillar keeps only its adapter (``ProwlerScanner``), its normalizer, and its
registry hooks (legacy snapshot write + account-link verification).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="cloud_posture.run_prowler_scan_for_account",
    # DEPRECATED transition shim — lossless-deploy hygiene only. Messages for
    # this task may still sit in the broker from a pre-spine beat fan-out when
    # the new code rolls out; dropping the task name would poison them. It
    # re-routes the request through the gated spine dispatch (so a duplicate
    # burst hits the cooldown, not Prowler). Remove after one deploy cycle.
    queue="cloud_posture",
    soft_time_limit=120,
    time_limit=180,
)
def run_prowler_scan_for_account(connection_id: str, account_id: str) -> dict[str, Any]:
    """DEPRECATED shim: forward a pre-spine per-account scan message onto the spine."""
    from components.cloud_posture.infrastructure.services.scan_dispatch_service import (
        dispatch_account_scan,
    )
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    connection = AwsOrganizationConnection.objects.filter(id=connection_id).first()
    if connection is None:
        logger.warning("cloud_posture_scan connection_not_found id=%s", connection_id)
        return {"success": False, "error": "connection_not_found"}

    verdict = dispatch_account_scan(connection, account_id, trigger="schedule")
    logger.info(
        "cloud_posture_legacy_shim_forwarded connection=%s account=%s enqueued=%s reason=%s",
        connection_id,
        account_id,
        verdict["enqueued"],
        verdict["reason"],
    )
    return {"success": True, "enqueued": verdict["enqueued"], "reason": verdict["reason"]}


#: How many drain waves one nightly sweep may chain before giving up. The cap
#: (``CLOUD_POSTURE_MAX_CONCURRENT_SCANS``) means a large org needs several
#: passes; without the chain a 200-account org at cap 10 would cover 10 accounts
#: a night and take three weeks to see itself once — recreating, as a "fix", the
#: exact silent-coverage failure this task family exists to remove. 60 waves at
#: the deferral interval (5 min) is about 5 hours, i.e. ~600 accounts inside one
#: nightly window. Bounded so a permanently-full cluster cannot chain forever.
MAX_DRAIN_WAVES = int(os.environ.get("CLOUD_POSTURE_MAX_DRAIN_WAVES", "60"))


@shared_task(name="cloud_posture.schedule_prowler_runs", soft_time_limit=240, time_limit=300)
def schedule_prowler_runs(wave: int = 0) -> dict[str, Any]:
    """Fan-out beat entry: gated spine dispatches for every scannable account of opted-in orgs.

    ``wave`` is the drain-chain depth, not something beat ever passes. When the
    global concurrency cap defers work, this task re-enqueues itself after the
    deferral interval to pick up what it could not fit. That interval is far
    below the per-account cooldown, so a drain wave can only reach accounts that
    have NOT been scanned this cycle — it never turns the nightly scan into a
    rolling one.
    """
    from components.cloud_posture.infrastructure.services.scan_dispatch_service import (
        DEFER_RETRY_AFTER_SECONDS,
        dispatch_connection_scans,
    )
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    flags = get_feature_flags_provider()
    scheduled = 0
    blocked = 0
    deferred = 0

    connections = AwsOrganizationConnection.objects.filter(status=AwsOrganizationConnection.Status.CONNECTED).only(
        "id", "workspace", "role_name", "external_id", "regions"
    )

    for connection in connections.iterator():
        try:
            if not flags.is_feature_enabled("feature.cloud_posture", workspace_id=connection.workspace_id):
                continue
        except Exception:
            logger.exception("cloud_posture flag check failed workspace=%s", connection.workspace_id)
            continue
        counts = dispatch_connection_scans(connection, trigger="schedule")
        scheduled += counts["enqueued"]
        blocked += counts["blocked"]
        deferred += counts["deferred"]

    next_wave = _chain_drain_wave(wave=wave, deferred=deferred, countdown=DEFER_RETRY_AFTER_SECONDS)

    logger.info(
        "schedule_cloud_posture_scans wave=%d scheduled=%d blocked=%d deferred=%d next_wave=%s",
        wave,
        scheduled,
        blocked,
        deferred,
        next_wave,
    )
    return {
        "success": True,
        "wave": wave,
        "scheduled": scheduled,
        "blocked": blocked,
        "deferred": deferred,
        "next_wave_scheduled": next_wave,
    }


def _chain_drain_wave(*, wave: int, deferred: int, countdown: int) -> bool:
    """Queue the follow-up sweep that picks up what the cap deferred.

    Returns whether one was queued. Never raises: a chaining failure must not
    fail the sweep that already dispatched real work — the next nightly beat is
    the fallback either way.
    """
    if deferred <= 0:
        return False
    if wave + 1 >= MAX_DRAIN_WAVES:
        # Loud, because reaching here means the cluster stayed saturated for
        # hours and some accounts genuinely went unscanned this cycle.
        logger.warning(
            "cloud_posture drain chain exhausted after %d waves with %d accounts still deferred; "
            "raise CLOUD_POSTURE_MAX_CONCURRENT_SCANS or add scanner capacity",
            MAX_DRAIN_WAVES,
            deferred,
        )
        return False
    try:
        schedule_prowler_runs.apply_async(kwargs={"wave": wave + 1}, countdown=countdown)
    except Exception:
        logger.exception("cloud_posture drain wave enqueue failed wave=%d deferred=%d", wave + 1, deferred)
        return False
    return True
