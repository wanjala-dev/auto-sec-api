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
