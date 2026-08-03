"""Celery tasks: materialize the per-finding contextual-risk scores off the request path.

The heavy 4-signal blend (ADR 0013) always runs here, never inline in a request (§6 HARD
RULE). ``recompute_finding_risk`` rescores a whole workspace (feed-refresh fan-out /
on-demand); ``rescore_finding`` rescores one finding (the FindingRaised/FindingResolved
event path). Both are idempotent (recompute-not-increment).
"""

from __future__ import annotations

import logging
from uuid import UUID

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="findings.recompute_finding_risk", soft_time_limit=300, time_limit=360)
def recompute_finding_risk(workspace_id: str) -> dict:
    """Rescore every finding in a workspace against the latest EPSS/KEV + exposure."""
    from components.findings.application.providers.finding_provider import FindingProvider

    logger.info("recompute_finding_risk started workspace_id=%s", workspace_id)
    scored = FindingProvider.build_recompute_finding_risk_use_case().execute(UUID(workspace_id), timezone.now())
    return {"success": True, "workspace_id": workspace_id, "scored": scored}


@shared_task(name="findings.rescore_finding", soft_time_limit=60, time_limit=90)
def rescore_finding(workspace_id: str, finding_id: str) -> dict:
    """Rescore a single finding (a finding changed → rescore just it)."""
    from components.findings.application.providers.finding_provider import FindingProvider

    scored = FindingProvider.build_recompute_finding_risk_use_case().execute(
        UUID(workspace_id), timezone.now(), finding_id=UUID(finding_id)
    )
    return {"success": True, "finding_id": finding_id, "scored": scored}
