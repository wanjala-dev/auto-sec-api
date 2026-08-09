"""Scheduled Vercel posture re-scan fan-out (ADR 0021 D3 — the beat trigger).

Beat entry: for every CONNECTED VercelConnection whose workspace opted into
``feature.vercel_posture``, trigger one Prowler ``vercel`` scan of the
connection's consented team. Self-gates on the flag (D6: no scan Jobs run dark)
AND on the scanning dispatch gate (cooldown / in-flight — the beat never
double-dispatches over a manual scan). Rides the spine: the trigger use case
routes through ``dispatch_scan`` → the generic ``run_scan`` task, so every run
is a ``ScanRun`` row with trigger="schedule" provenance.

Deliberately a SEPARATE module from ``cloud_posture_tasks`` — that file is the
legacy AWS pipeline (scheduled for the spine migration, audit R1); nothing here
copies its choreography.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)

_FLAG = "feature.vercel_posture"


@shared_task(name="cloud_posture.schedule_vercel_prowler_runs", soft_time_limit=240, time_limit=300)
def schedule_vercel_prowler_runs() -> dict[str, Any]:
    """Fan out Vercel posture scans over opted-in workspaces' connected teams."""
    from components.cloud_posture.application.providers.scan_provider import trigger_vercel_scan
    from components.cloud_posture.application.use_cases.trigger_vercel_scan_use_case import (
        VercelScanRejected,
    )
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )
    from infrastructure.persistence.integrations.models import VercelConnection

    flags = get_feature_flags_provider()
    scheduled = 0
    skipped = 0

    connections = VercelConnection.objects.filter(status=VercelConnection.Status.CONNECTED).only(
        "id", "workspace", "team_id", "team_slug"
    )
    for connection in connections.iterator():
        try:
            # Fail closed: a flag-check error means NO scan (D6), mirroring the
            # AWS beat's posture.
            if not flags.is_feature_enabled(_FLAG, workspace_id=connection.workspace_id):
                continue
        except Exception:
            logger.exception("vercel_posture flag check failed workspace=%s", connection.workspace_id)
            continue
        team = connection.team_ref
        if not team:
            logger.warning("vercel_posture_beat_no_team connection=%s", connection.id)
            continue
        try:
            trigger_vercel_scan(
                workspace_id=connection.workspace_id,
                connection_id=connection.id,
                team=team,
                trigger="schedule",  # provenance: the beat, not an operator
            )
            scheduled += 1
        except VercelScanRejected as exc:
            # In-flight or cooldown — expected overlap with a manual scan; skip quietly.
            logger.info("vercel_posture_beat_skipped connection=%s reason=%s", connection.id, exc.code)
            skipped += 1
        except Exception:
            # One broken connection must not stop the fan-out.
            logger.exception("vercel_posture_beat_dispatch_failed connection=%s", connection.id)

    logger.info("schedule_vercel_prowler_runs scheduled=%d skipped=%d", scheduled, skipped)
    return {"success": True, "scheduled": scheduled, "skipped": skipped}
