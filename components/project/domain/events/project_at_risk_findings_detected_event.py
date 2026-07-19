"""Domain event: the monthly project-at-risk detector found one or more
projects with a meaningful overdue-task backlog.

Phase 5a (N=3 specialist migration) of the Agents-as-Teammates migration
(``docs/plans/AGENTS_AS_TEAMMATES_MIGRATION.md``). Same shape as the
Phase 3 ``BookBalanceFindingsDetected`` and
``BudgetVarianceFindingsDetected`` events: one emission per
(workspace, detector_run) carrying every finding, with the period as
the dedup key.

The project-at-risk specialist handler subscribes to this event and
turns each finding into a Task on the workspace's AI agent team
Kanban (with a shadow ``AIAction`` for the legacy ``/ai/actions/``
read endpoint).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from components.shared_kernel.domain.events import DomainEvent


@dataclass(frozen=True, kw_only=True)
class ProjectAtRiskFindingsDetected(DomainEvent):
    """Findings emitted by one project-at-risk run for one workspace.

    ``findings`` is a tuple of dicts. Each dict carries:

    * ``project_id`` (str) — Project.pk (UUID-serialised)
    * ``project_title`` (str)
    * ``team_title`` (str)
    * ``overdue_task_count`` (int)
    * ``period`` (str) — ``YYYY-MM`` (dedup key paired with project_id)
    * ``impact_score`` (int) — 30/50/70/90 by backlog size
    """

    workspace_id: UUID
    detector_key: str
    period: str
    findings: tuple[dict[str, Any], ...] = field(default_factory=tuple)
