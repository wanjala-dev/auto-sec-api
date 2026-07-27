"""Celery task: recompute a workspace's ATT&CK coverage heatmap off the request path."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="findings.recompute_attck_coverage", soft_time_limit=120, time_limit=180)
def recompute_workspace_attck_coverage(workspace_id: str) -> dict:
    """Aggregate the workspace's open findings by ATT&CK technique into the
    materialized heatmap row. Idempotent — safe to enqueue repeatedly."""
    from components.findings.application.providers.finding_provider import FindingProvider

    logger.info("recompute_attck_coverage started workspace_id=%s", workspace_id)
    coverage = FindingProvider.build_recompute_attck_coverage_use_case().execute(
        UUID(workspace_id), datetime.now(UTC)
    )
    return {"success": True, "techniques": coverage["totals"]["techniques"]}
