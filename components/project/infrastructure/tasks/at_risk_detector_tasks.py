"""Celery task for the project-at-risk detector.

Scheduled weekly (Wednesday 07:00 UTC) — one day after sponsor churn so
findings spread out across the week rather than piling onto the board
on any single morning. Idempotent — see
``components/project/infrastructure/services/at_risk_detector_service.py``.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name="project.detect_at_risk_projects_for_all_workspaces",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    retry_backoff=True,
    retry_jitter=True,
    time_limit=600,
    soft_time_limit=540,
)
def detect_at_risk_projects_for_all_workspaces(self) -> dict[str, int]:
    """Fan out project-at-risk detection across every active workspace."""
    from infrastructure.persistence.workspaces.models import Workspace
    from components.project.infrastructure.services.at_risk_detector_service import (
        report_at_risk_projects,
    )

    logger.info(
        "detect_at_risk_projects_for_all_workspaces started task_id=%s",
        self.request.id,
    )
    workspaces_scanned = 0
    findings_emitted = 0
    errors = 0
    queryset = Workspace.objects.filter(is_active=True).only("id")
    for workspace in queryset.iterator(chunk_size=200):
        workspaces_scanned += 1
        try:
            findings_emitted += report_at_risk_projects(workspace)
        except Exception:
            errors += 1
            logger.exception(
                "project_at_risk_detector_failed workspace_id=%s",
                workspace.id,
            )
    logger.info(
        "detect_at_risk_projects_for_all_workspaces completed task_id=%s "
        "workspaces_scanned=%s findings_emitted=%s errors=%s",
        self.request.id, workspaces_scanned, findings_emitted, errors,
    )
    return {
        "workspaces_scanned": workspaces_scanned,
        "findings_emitted": findings_emitted,
        "errors": errors,
    }


@shared_task(
    name="project.detect_at_risk_projects_for_workspace",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_jitter=True,
    time_limit=120,
)
def detect_at_risk_projects_for_workspace(self, workspace_id: str) -> int:
    """Run the at-risk detector for a single workspace."""
    from infrastructure.persistence.workspaces.models import Workspace
    from components.project.infrastructure.services.at_risk_detector_service import (
        report_at_risk_projects,
    )

    logger.info(
        "detect_at_risk_projects_for_workspace started workspace_id=%s "
        "task_id=%s",
        workspace_id, self.request.id,
    )
    workspace = Workspace.objects.filter(id=workspace_id).first()
    if workspace is None:
        logger.warning(
            "detect_at_risk_projects_for_workspace workspace_missing "
            "workspace_id=%s",
            workspace_id,
        )
        return 0
    emitted = report_at_risk_projects(workspace)
    logger.info(
        "detect_at_risk_projects_for_workspace completed workspace_id=%s "
        "findings_emitted=%s",
        workspace_id, emitted,
    )
    return emitted
