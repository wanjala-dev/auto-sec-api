"""Celery Beat entry point for the remediation bounded context (ADR 0012 P4a).

Beat-scheduled tasks are PRIMARY ADAPTERS — the scheduler is an external trigger
driving the application, like an HTTP request or CLI command. This is a thin
wrapper that delegates to the infrastructure reconciler; it holds no business
logic itself.

``reconcile_merged_remediations`` sweeps every finding carrying an OPEN draft PR,
verifies each PR's merge via the integrations ``VcsPort``, and — on a verified
merge — resolves the finding and offers the fix to the D1 entry-gate with a
VERIFIED ``pr_applied=True``. Idempotent (already-resolved findings and findings
already holding a RemediationEntry are no-ops), so re-running the task is safe.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="remediation.reconcile_merged_remediations",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
    time_limit=1800,
    soft_time_limit=1620,
)
def reconcile_merged_remediations(self) -> dict[str, Any]:
    """Reconcile merged remediation PRs → resolved findings + gated corpus entries."""
    from components.remediation.infrastructure.tasks.reconcile_tasks import (
        run_reconcile_merged_remediations,
    )

    logger.info("reconcile_merged_remediations started task_id=%s", self.request.id)
    counts = run_reconcile_merged_remediations()
    logger.info(
        "reconcile_merged_remediations completed task_id=%s scanned=%s merged=%s resolved=%s captured=%s",
        self.request.id,
        counts["scanned"],
        counts["merged"],
        counts["resolved"],
        counts["captured"],
    )
    return counts
