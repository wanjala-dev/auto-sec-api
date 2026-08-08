"""Adapter: read a draft-PR finding's facts from ``project.Task``.

Implements :class:`FindingFactsPort`. Same sanctioned cross-context read pattern
the ``report`` (``FindingSourcePort`` → ``BoardFindingRepository``) and
``remediation`` (``FindingRemediationFactsPort`` → ``BoardFindingFactsRepository``)
contexts use: the integrations context defines its own port shaped to the draft-PR
flow's need, and this infrastructure adapter reads the shared ``project``
persistence model. Reading ``infrastructure.persistence.project.models`` is a
persistence read, NOT a ``components.project.infrastructure`` import — it does not
cross the component-infrastructure boundary the architecture tests guard.

The source-type gate (the draft-PR-actionable sources: ``ai.log_watch`` +
``ai.code_security``, ADR 0019 P2) and workspace scope live here, matching the old
inline ``_require_actionable_finding`` query: a task from another workspace, of a
non-actionable source type, or with a malformed id resolves to ``None``.
"""

from __future__ import annotations

from components.integrations.application.ports.finding_facts_port import (
    ActionableFinding,
    FindingFactsPort,
)

# The finding sources the ONE draft-PR engine acts on (ADR 0017 D0). A new source
# joins this tuple together with its patch strategy in the use case — never a
# second engine.
ACTIONABLE_SOURCES = ("ai.log_watch", "ai.code_security")


class BoardFindingFactsReader(FindingFactsPort):
    def get_actionable_finding(self, *, workspace_id: str, task_id: str) -> ActionableFinding | None:
        from infrastructure.persistence.project.models import Task

        try:
            row = Task.objects.filter(id=task_id, workspace_id=workspace_id, source_type__in=ACTIONABLE_SOURCES).first()
        except (ValueError, TypeError):
            # Malformed id (Task pks are integers) — same answer as absent.
            row = None
        if row is None:
            return None
        return ActionableFinding(
            id=str(row.id),
            title=row.title,
            metadata=row.metadata or {},
            source_type=row.source_type or "",
        )

    def count_open_draft_prs(self, *, workspace_id: str, source_type: str, repo: str) -> int:
        """Open (recorded, unresolved) draft PRs for ``source_type`` against ``repo``.

        A merged PR's finding is resolved by the remediation reconciler
        (``metadata.triage.status = "resolved"`` / ``payload.resolved``), which
        removes it from this count — the throttle window frees as PRs land.
        """
        from infrastructure.persistence.project.models import Task

        rows = Task.objects.filter(
            workspace_id=workspace_id,
            source_type=source_type,
            metadata__payload__draft_pr__repo=repo,
        ).values_list("metadata", flat=True)
        open_count = 0
        for metadata in rows:
            meta = metadata or {}
            payload = meta.get("payload") or {}
            if not (payload.get("draft_pr") or {}).get("url"):
                continue
            triage = meta.get("triage") or {}
            if str(triage.get("status", "")).lower() == "resolved" or payload.get("resolved"):
                continue
            open_count += 1
        return open_count
