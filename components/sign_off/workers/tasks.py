"""Celery Beat entry point for the sign-off bounded context.

Beat-scheduled tasks are PRIMARY ADAPTERS — the scheduler is an external
trigger driving the application, just like an HTTP request or CLI
command. This module is a thin wrapper that delegates to the sign-off
application service.

``materialize_pending_signoff_tasks`` runs on a periodic cadence. It
sweeps every workspace that has an Agents team and projects that
workspace's pending sign-off queue onto its "AI Findings" Kanban board
(assigned to the owner), and reconciles cards whose artifact has left the
pending set. The service is idempotent (``persist_finding_as_task``
short-circuits on a matching idempotency key; the reconcile leaves cards
already in the right column untouched), so re-running the task is safe.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="sign_off.materialize_pending_signoff_tasks",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    time_limit=1800,
    soft_time_limit=1620,
)
def materialize_pending_signoff_tasks(self) -> dict[str, int]:
    """Sweep all workspaces, projecting pending sign-offs onto the AI board."""
    from components.sign_off.application.services.materialize_signoff_tasks import (
        materialize_all_pending_signoff_tasks,
    )

    logger.info(
        "materialize_pending_signoff_tasks started task_id=%s", self.request.id
    )
    totals = materialize_all_pending_signoff_tasks()
    logger.info(
        "materialize_pending_signoff_tasks completed task_id=%s "
        "workspaces=%s created=%s reconciled_accepted=%s "
        "reconciled_dismissed=%s errors=%s",
        self.request.id, totals["workspaces"], totals["created"],
        totals["reconciled_accepted"], totals["reconciled_dismissed"],
        totals["errors"],
    )
    return totals
