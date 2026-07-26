"""Scheduled container-scan fan-out (ADR 0006 — the periodic-rescan trigger).

Beat entry: for every workspace opted into ``feature.container_security``, enqueue a
Trivy scan per known container image (the "rescan patched images" cadence — mirrors
trivy-operator's continuous cadence and the cloud_posture beat fan-out). Self-gates on
the flag; dark until opt-in.

Image inventory comes from the CNAPP asset graph (discovered ECR images) — wired via
``_image_targets_for_workspace``. Until that source lands it returns nothing, so the
schedule is a safe no-op rather than scanning arbitrary images.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)

_SOURCE = "container_security.trivy"


@shared_task(name="container_security.schedule_container_scans", soft_time_limit=240, time_limit=300)
def schedule_container_scans() -> dict[str, Any]:
    """Fan out Trivy scans over opted-in workspaces' known images."""
    from components.scanning.application.providers.scan_dispatch_provider import dispatch_scan
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )
    from infrastructure.persistence.workspaces.models import Workspace

    flags = get_feature_flags_provider()
    scheduled = 0
    for workspace in Workspace.active.only("id").iterator():
        try:
            if not flags.is_feature_enabled("feature.container_security", workspace_id=workspace.id):
                continue
        except Exception:
            logger.exception("container_security flag check failed workspace=%s", workspace.id)
            continue
        for image_ref, connection_id, account_id in _image_targets_for_workspace(workspace.id):
            dispatch_scan(
                source=_SOURCE,
                workspace_id=str(workspace.id),
                target_ref=image_ref,
                connection_id=connection_id,
                account_id=account_id,
            )
            scheduled += 1

    logger.info("schedule_container_scans scheduled=%d", scheduled)
    return {"success": True, "scheduled": scheduled}


def _image_targets_for_workspace(workspace_id) -> list[tuple[str, str | None, str]]:
    """Return (image_ref, connection_id, account_id) tuples to scan for a workspace.

    Seam for the image inventory. TODO: query the CNAPP asset graph for discovered
    container/ECR image assets (ties container scanning to the asset graph). Empty until
    then — the schedule stays a safe no-op rather than guessing at images.
    """
    return []
