"""Composition root for the on-demand CSPM scan trigger.

The single public seam other contexts use to kick a scan for a connection — the
integrations "Scan now" endpoint resolves it here rather than importing the
cloud-posture dispatch service directly. Provider files are the allowed slot for
own-context infrastructure imports (the composition root). Dispatches are gated
(cooldown + single-in-flight, audit R1) and enqueued onto the spine's Celery
task; Prowler never runs in the request path.
"""

from __future__ import annotations


def enqueue_connection_scan(
    *, workspace_id: str, connection_id: str, triggered_by=None, trigger: str = "manual"
) -> dict | None:
    """Gate + enqueue async scans for a workspace's connection.

    ``triggered_by`` is the operator's user id — stamped onto every ``ScanRun``
    the fan-out creates (the provenance the scan-now controller used to drop).
    ``trigger`` is the coarse origin: ``manual`` (an operator pressed Scan now,
    the default), or ``verify`` when a successful connection verification kicked
    the first scan itself. The beat fan-out passes ``schedule`` through the
    dispatch service directly.

    Returns ``{"scannable", "enqueued", "blocked", "deferred", "retry_after"}``,
    or ``None`` when no such connection belongs to the workspace (→ 404).
    """
    from components.cloud_posture.infrastructure.services.scan_dispatch_service import (
        dispatch_scans_for_workspace_connection,
    )

    return dispatch_scans_for_workspace_connection(
        workspace_id=workspace_id,
        connection_id=connection_id,
        trigger=trigger,
        triggered_by=triggered_by,
    )


def trigger_vercel_scan(*, workspace_id, connection_id, team: str, trigger: str = "manual", triggered_by=None) -> dict:
    """Gate + dispatch one Vercel posture scan (ADR 0021 D3) — the seam the
    integrations "Scan now" endpoint and the beat fan-out both call. Raises
    ``VercelScanRejected`` (import it from the use case) on a gate rejection."""
    from components.cloud_posture.application.use_cases.trigger_vercel_scan_use_case import (
        TriggerVercelScanUseCase,
    )

    return TriggerVercelScanUseCase().execute(
        workspace_id=workspace_id,
        connection_id=connection_id,
        team=team,
        trigger=trigger,
        triggered_by=triggered_by,
    )
