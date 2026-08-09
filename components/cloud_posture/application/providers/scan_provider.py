"""Composition root for the on-demand CSPM scan trigger.

The single public seam other contexts use to kick a scan for a connection — the
integrations "Scan now" endpoint resolves it here rather than importing the
cloud-posture Celery task directly. Provider files are the allowed slot for
own-context infrastructure imports (the composition root). The work is enqueued
onto Celery and this returns immediately; it never runs Prowler inline.
"""

from __future__ import annotations


def enqueue_connection_scan(*, workspace_id: str, connection_id: str) -> int | None:
    """Enqueue async scans for a workspace's connection.

    Returns the number of per-account scans enqueued, or ``None`` when no such
    connection belongs to the workspace (the caller maps that to 404).
    """
    from components.cloud_posture.infrastructure.tasks.cloud_posture_tasks import (
        enqueue_scan_for_connection,
    )

    return enqueue_scan_for_connection(workspace_id=workspace_id, connection_id=connection_id)


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
