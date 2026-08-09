"""Composition root for the on-demand CSPM scan trigger.

The single public seam other contexts use to kick a scan for a connection — the
integrations "Scan now" endpoint resolves it here rather than importing the
cloud-posture dispatch service directly. Provider files are the allowed slot for
own-context infrastructure imports (the composition root). Dispatches are gated
(cooldown + single-in-flight, audit R1) and enqueued onto the spine's Celery
task; Prowler never runs in the request path.
"""

from __future__ import annotations


def enqueue_connection_scan(*, workspace_id: str, connection_id: str, triggered_by=None) -> dict | None:
    """Gate + enqueue async scans for a workspace's connection (trigger=manual).

    ``triggered_by`` is the operator's user id — stamped onto every ``ScanRun``
    the fan-out creates (the provenance the scan-now controller used to drop).
    Returns ``{"enqueued": n, "blocked": m, "retry_after": seconds-or-None}``,
    or ``None`` when no such connection belongs to the workspace (→ 404).
    """
    from components.cloud_posture.infrastructure.services.scan_dispatch_service import (
        dispatch_scans_for_workspace_connection,
    )

    return dispatch_scans_for_workspace_connection(
        workspace_id=workspace_id,
        connection_id=connection_id,
        trigger="manual",
        triggered_by=triggered_by,
    )
