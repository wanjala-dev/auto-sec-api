"""Project-at-risk specialist: turn ``ProjectAtRiskFindingsDetected``
into Tasks on the workspace's AI agent team Kanban.

Phase 5a (N=3) of the Agents-as-Teammates migration. Same shape as
Phase 3a (book balance) and 3b (budget variance) — all share the
``persist_finding_as_task`` step. The per-finding shape and
idempotency key differ (``project_id`` instead of ``kind`` or
``category_id``), which is why this is a sibling handler rather than
a parameter on the others.

Idempotency: ``(workspace, source_type, metadata.idempotency_key)``
where the key is ``project_id:<project_id>:period:<period>`` —
re-running the detector the same month for the same workspace is a
no-op.

Failure isolation: each finding is wrapped in its own try/except so
one bad finding doesn't void the rest. Exceptions are logged with the
project id; nothing re-raises (the originating detector run already
returned).
"""
from __future__ import annotations

import logging

from components.agents.application.handlers.specialist_persistence_service import (
    persist_finding_as_task,
)
from components.agents.application.subscription_registry_service import subscribes_to
from components.project.domain.events.project_at_risk_findings_detected_event import (
    ProjectAtRiskFindingsDetected,
)

logger = logging.getLogger(__name__)

AGENT_TYPE = "project_specialist"
DETECTOR_KEY = "project_overdue_task_backlog"
ACTION_TYPE = "project_at_risk"


@subscribes_to(ProjectAtRiskFindingsDetected)
def handle_project_at_risk_findings_detected(
    event: ProjectAtRiskFindingsDetected,
) -> None:
    """Persist each at-risk project finding as a Task.

    Lazy imports keep this module import-cheap so wiring in
    ``apps.py.ready()`` doesn't drag the ORM into every worker
    bootstrap.
    """
    from infrastructure.persistence.workspaces.models import Workspace

    from components.agents.application.facades.ai_teammate_facade import (
        ensure_agents_board,
    )
    from components.agents.infrastructure.services.agents_board_service import (
        SUGGESTED,
    )

    workspace = Workspace.objects.filter(id=event.workspace_id).first()
    if workspace is None:
        logger.warning(
            "project_at_risk_workspace_missing workspace_id=%s period=%s",
            event.workspace_id, event.period,
        )
        return

    if not event.findings:
        logger.info(
            "project_at_risk_no_findings workspace_id=%s period=%s",
            event.workspace_id, event.period,
        )
        return

    board = ensure_agents_board(workspace)
    suggested_column = board.column(SUGGESTED)
    ai_user_id = str(board.team.created_by_id)

    persisted = 0
    skipped = 0
    failed = 0
    for finding in event.findings:
        project_id = finding.get("project_id") or ""

        project_title = finding.get("project_title") or "Project"
        overdue_count = int(finding.get("overdue_task_count") or 0)
        team_title = finding.get("team_title") or ""
        team_label = f" ({team_title})" if team_title else ""
        title = (
            f"{project_title} has {overdue_count} "
            f"overdue task{'s' if overdue_count != 1 else ''}"
        )
        summary = (
            f"Project {project_title}{team_label} has {overdue_count} "
            "tasks past their due date and still open. Review with the "
            "team lead — reschedule or reassign to unblock progress."
        )
        context = {
            "project_id": project_id,
            "period": event.period,
            "detector_key": event.detector_key,
        }
        payload_data = {
            "project_id": project_id,
            "project_title": project_title,
            "team_title": team_title,
            "overdue_task_count": overdue_count,
        }

        try:
            task_id = persist_finding_as_task(
                workspace=workspace,
                suggested_column=suggested_column,
                ai_user_id=ai_user_id,
                title=title,
                summary=summary,
                source_type=f"ai.{ACTION_TYPE}",
                agent_type=AGENT_TYPE,
                detector_key=DETECTOR_KEY,
                payload_data=payload_data,
                context=context,
                impact_score=int(finding.get("impact_score") or 0),
                idempotency_key=f"project_id:{project_id}:period:{event.period}",
            )
            if task_id is None:
                skipped += 1
                continue
            persisted += 1
            logger.info(
                "project_at_risk_finding_persisted workspace_id=%s "
                "period=%s project_id=%s overdue=%d task_id=%s",
                workspace.id, event.period, project_id,
                overdue_count, task_id,
            )
        except Exception:
            failed += 1
            logger.exception(
                "project_at_risk_finding_persist_failed workspace_id=%s "
                "period=%s project_id=%s",
                workspace.id, event.period, project_id,
            )

    logger.info(
        "project_at_risk_findings_handled workspace_id=%s period=%s "
        "persisted=%d skipped=%d failed=%d",
        workspace.id, event.period, persisted, skipped, failed,
    )
