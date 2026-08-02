"""Adapter: read a draft-PR finding's facts from ``project.Task``.

Implements :class:`FindingFactsPort`. Same sanctioned cross-context read pattern
the ``report`` (``FindingSourcePort`` → ``BoardFindingRepository``) and
``remediation`` (``FindingRemediationFactsPort`` → ``BoardFindingFactsRepository``)
contexts use: the integrations context defines its own port shaped to the draft-PR
flow's need, and this infrastructure adapter reads the shared ``project``
persistence model. Reading ``infrastructure.persistence.project.models`` is a
persistence read, NOT a ``components.project.infrastructure`` import — it does not
cross the component-infrastructure boundary the architecture tests guard.

The source-type gate (``ai.log_watch``) and workspace scope live here, matching the
old inline ``_require_actionable_finding`` query exactly: a task from another
workspace, of another source type, or with a malformed id resolves to ``None``.
"""

from __future__ import annotations

from components.integrations.application.ports.finding_facts_port import (
    ActionableFinding,
    FindingFactsPort,
)

_LOG_WATCH_SOURCE = "ai.log_watch"


class BoardFindingFactsReader(FindingFactsPort):
    def get_actionable_finding(self, *, workspace_id: str, task_id: str) -> ActionableFinding | None:
        from infrastructure.persistence.project.models import Task

        try:
            row = Task.objects.filter(id=task_id, workspace_id=workspace_id, source_type=_LOG_WATCH_SOURCE).first()
        except (ValueError, TypeError):
            # Malformed id (Task pks are integers) — same answer as absent.
            row = None
        if row is None:
            return None
        return ActionableFinding(id=str(row.id), title=row.title, metadata=row.metadata or {})
