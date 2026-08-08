"""Adapter: read-only board-task lookups from ``project.Task``.

Implements :class:`TaskLookupPort`. This is the ``project`` context reading its
OWN persistence model (``infrastructure.persistence.project.models``) behind its
own application port — the sanctioned inbound read seam other contexts consume,
mirroring ``BoardFindingFactsRepository`` in ``remediation``. Reading
``project``'s persistence models from ``project``'s infrastructure does not cross
the component-infrastructure boundary the architecture tests guard.

Both reads are workspace-scoped (tenant isolation) and use ``.only(...)`` to pull
just the columns the caller consumes.
"""

from __future__ import annotations

from uuid import UUID

from components.project.application.ports.record_finding_draft_pr_port import get_draft_pr
from components.project.application.ports.task_lookup_port import (
    DraftPrFinding,
    TaskLookupPort,
)


class OrmTaskLookupRepository(TaskLookupPort):
    def find_by_idempotency(self, *, workspace_id: str, source_type: str, key: str) -> UUID | None:
        # An empty idempotency key never matches — callers without an
        # idempotency contract skip the check, and a blank key must not collide
        # with other blank-keyed rows.
        if not key:
            return None

        from infrastructure.persistence.project.models import Task

        return (
            Task.objects.filter(
                workspace_id=workspace_id,
                source_type=source_type,
                metadata__idempotency_key=key,
            )
            .values_list("id", flat=True)
            .first()
        )

    def list_draft_pr_findings(self, *, workspace_id: str) -> list[DraftPrFinding]:
        from infrastructure.persistence.project.models import Task

        findings: list[DraftPrFinding] = []
        tasks = (
            Task.objects.filter(workspace_id=str(workspace_id), source_type__startswith="ai.")
            .only("id", "title", "metadata")
            .iterator(chunk_size=500)
        )
        for task in tasks:
            draft_pr = get_draft_pr(task.metadata)
            if not draft_pr.get("url"):
                continue
            findings.append(
                DraftPrFinding(
                    task_id=task.id,
                    title=task.title,
                    url=str(draft_pr.get("url") or ""),
                    repo=str(draft_pr.get("repo") or ""),
                    branch=str(draft_pr.get("branch") or ""),
                    opened_by=draft_pr.get("opened_by"),
                    opened_at=draft_pr.get("opened_at"),
                )
            )
        return findings
