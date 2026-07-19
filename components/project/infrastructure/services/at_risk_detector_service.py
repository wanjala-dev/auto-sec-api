"""Detects projects that look off-track and emits a domain event the
project-at-risk specialist handler turns into Kanban tasks.

Phase 5 of the Agents-as-Teammates migration
(``docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md``) retired ``AIAction``;
this detector emits ``ProjectAtRiskFindingsDetected`` and the matching
specialist handler subscribes via the
``persist_finding_as_task`` helper to write a single Kanban task per
finding on the workspace's AI agent team board.

Logic for v1: a project is flagged as at-risk when it has
``MIN_OVERDUE_TASKS`` or more tasks in todo status whose ``due_date`` has
passed. That's a simple, high-precision signal — any serious backlog
deserves a check-in, and the number is easy to explain to admins.

Later iterations could layer in:
- Projects approaching their ``end_date`` with many open tasks.
- Projects with no recent task updates (staleness).
- Projects where the lead has no open tasks themselves (stuck on someone
  else's plate).

All of these follow the same pattern; each would add a ``detector``
value rather than a new emitter.

Idempotency key: ``(workspace, action_type, project_id, month)`` — re-runs
within the same month are no-ops, but next month emits fresh signal
because the month rolls. Enforced on the handler side.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)

MIN_OVERDUE_TASKS = 3
DETECTOR_KEY = "project_overdue_task_backlog"
ACTION_TYPE = "project_at_risk"
AGENT_TYPE = "project_agent"


@dataclass(frozen=True)
class ProjectAtRiskFinding:
    project_id: str
    project_title: str
    team_title: str
    overdue_task_count: int
    period: str  # "YYYY-MM"


def detect_at_risk_projects(
    workspace,
    *,
    as_of: date | None = None,
) -> list[ProjectAtRiskFinding]:
    """Return projects with >= ``MIN_OVERDUE_TASKS`` overdue todo tasks."""
    from django.db.models import Count, Q
    from infrastructure.persistence.project.models import Project, Task

    today = as_of or date.today()
    period = f"{today.year:04d}-{today.month:02d}"

    # Annotate each project with its count of overdue, non-done tasks —
    # one query instead of N.
    overdue_filter = Q(
        tasks__due_date__lt=today,
        tasks__due_date__isnull=False,
    ) & ~Q(tasks__status__in=(Task.DONE, Task.ARCHIVED))

    qs = (
        Project.objects.filter(workspace=workspace)
        .select_related("team")
        .annotate(overdue_count=Count("tasks", filter=overdue_filter))
        .filter(overdue_count__gte=MIN_OVERDUE_TASKS)
        .only("id", "title", "team__title")
    )
    findings: list[ProjectAtRiskFinding] = []
    for project in qs.iterator(chunk_size=200):
        findings.append(
            ProjectAtRiskFinding(
                project_id=str(project.id),
                project_title=project.title,
                team_title=project.team.title if project.team else "",
                overdue_task_count=project.overdue_count,
                period=period,
            )
        )
    return findings


def report_at_risk_projects(workspace, *, as_of: date | None = None) -> int:
    """Detect at-risk projects for *workspace* and emit a
    ``ProjectAtRiskFindingsDetected`` domain event. Returns the number
    of findings in this run.

    Idempotency on ``(workspace, action_type, project_id, period)`` is
    the handler's responsibility — re-running the detector twice in the
    same month for the same workspace is a no-op.
    """
    findings = detect_at_risk_projects(workspace, as_of=as_of)
    if not findings:
        return 0

    findings_payload = tuple(
        {
            "project_id": f.project_id,
            "project_title": f.project_title,
            "team_title": f.team_title,
            "overdue_task_count": f.overdue_task_count,
            "period": f.period,
            "impact_score": _overdue_impact_score(f.overdue_task_count),
        }
        for f in findings
    )
    period = findings[0].period

    from components.project.domain.events.project_at_risk_findings_detected_event import (
        ProjectAtRiskFindingsDetected,
    )
    from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
        CeleryEventPublisher,
    )

    event = ProjectAtRiskFindingsDetected(
        workspace_id=workspace.id,
        detector_key=DETECTOR_KEY,
        period=period,
        findings=findings_payload,
    )
    try:
        CeleryEventPublisher().publish(event)
    except Exception:
        logger.exception(
            "project_at_risk_event_publish_failed workspace_id=%s period=%s",
            workspace.id, period,
        )
        return len(findings_payload)

    logger.info(
        "project_at_risk_findings_emitted workspace_id=%s period=%s count=%d",
        workspace.id, period, len(findings_payload),
    )
    return len(findings_payload)


def _overdue_impact_score(overdue_count: int) -> int:
    """Higher impact as backlog grows. Hits High-impact chip (60+) at 5+."""
    if overdue_count >= 10:
        return 90
    if overdue_count >= 5:
        return 70
    if overdue_count >= 3:
        return 50
    return 30
