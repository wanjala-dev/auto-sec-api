"""Scheduled SAST re-scan fan-out (ADR 0019 D3 — the beat trigger).

Beat entry: for every workspace opted into ``feature.code_security``, enqueue one
Opengrep scan per allowlisted repo of its CONNECTED VcsConnections (via the
integrations seam — the allowlist IS the consent boundary). Self-gates on the
flag; dark until opt-in — the P1 trigger answer is manual + nightly-when-flag-on.

Fingerprint-based identity (D4) makes the nightly re-scan cheap on the SSOT:
unchanged findings bump ``last_seen``, fixed ones stop being observed and the
existing resolve machinery closes them, new ones are genuinely new.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)

_SOURCE = "code_security.opengrep"


@shared_task(name="code_security.schedule_repo_scans", soft_time_limit=240, time_limit=300)
def schedule_repo_scans() -> dict[str, Any]:
    """Fan out Opengrep scans over opted-in workspaces' allowlisted repos."""
    from components.integrations.application.providers.vcs_scan_access_provider import (
        list_scannable_repos,
    )
    from components.scanning.application.providers.scan_dispatch_provider import dispatch_scan
    from components.shared_platform.application.providers.feature_flags_provider import (
        get_feature_flags_provider,
    )
    from infrastructure.persistence.workspaces.models import Workspace

    flags = get_feature_flags_provider()
    scheduled = 0
    for workspace in Workspace.active.only("id").iterator():
        try:
            if not flags.is_feature_enabled("feature.code_security", workspace_id=workspace.id):
                continue
        except Exception:
            logger.exception("code_security flag check failed workspace=%s", workspace.id)
            continue
        for repo, connection_id in list_scannable_repos(workspace.id):
            dispatch_scan(
                source=_SOURCE,
                workspace_id=str(workspace.id),
                target_ref=repo,
                connection_id=connection_id,
                trigger="schedule",  # provenance: the nightly beat, not an operator
            )
            scheduled += 1

    logger.info("schedule_repo_scans scheduled=%d", scheduled)
    return {"success": True, "scheduled": scheduled}
