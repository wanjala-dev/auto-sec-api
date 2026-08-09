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


@shared_task(name="cloud_posture.schedule_prowler_runs", soft_time_limit=240, time_limit=300)
def schedule_prowler_runs() -> dict[str, Any]:
    """Fan-out beat entry: gated spine dispatches for every scannable account of opted-in orgs."""
    from components.cloud_posture.infrastructure.services.scan_dispatch_service import (
        dispatch_connection_scans,
    )
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )
    from infrastructure.persistence.integrations.models import AwsOrganizationConnection

    flags = get_feature_flags_provider()
    scheduled = 0
    blocked = 0

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

    logger.info("schedule_cloud_posture_scans scheduled=%d blocked=%d", scheduled, blocked)
    return {"success": True, "scheduled": scheduled, "blocked": blocked}
