"""Adapter: enumerate board findings with an open, unresolved draft PR (ADR 0012 P4a).

Implements :class:`OpenDraftPrFindingsPort`. Scans ``project.Task`` for tasks
whose ``metadata.payload.draft_pr.url`` is set (a fix was proposed) and streams
them via ``.iterator(chunk_size=…)`` (performance rule §5). The "not yet
resolved" filter is applied in Python because ``triage.status`` lives in a JSON
blob whose absence must read as unresolved — a DB ``__triage__status`` predicate
would silently drop rows that have no triage key at all.

Same sanctioned board-read pattern as ``BoardFindingFactsRepository`` — a
persistence read of ``project.Task``, not a components.project.infrastructure
import.
"""

from __future__ import annotations

from collections.abc import Iterator

from components.remediation.application.ports.open_draft_pr_findings_port import (
    OpenDraftPrFinding,
    OpenDraftPrFindingsPort,
)


class BoardOpenDraftPrFindingsRepository(OpenDraftPrFindingsPort):
    def iter_open_draft_pr_findings(self, *, chunk_size: int = 500) -> Iterator[OpenDraftPrFinding]:
        from infrastructure.persistence.project.models import Task

        # DB-narrow to tasks that actually carry a draft-PR url; finalize the
        # unresolved + repo checks in Python off the JSON metadata.
        rows = (
            Task.objects.filter(metadata__payload__draft_pr__url__isnull=False)
            .only("id", "workspace_id", "metadata")
            .iterator(chunk_size=chunk_size)
        )
        for row in rows:
            metadata = row.metadata or {}
            triage = metadata.get("triage") or {}
            if str(triage.get("status", "")).lower() == "resolved":
                continue  # already resolved — not a candidate

            payload = metadata.get("payload") or {}
            draft_pr = payload.get("draft_pr") or {}
            url = draft_pr.get("url")
            if not url:
                continue

            yield OpenDraftPrFinding(
                workspace_id=str(row.workspace_id),
                finding_task_id=str(row.id),
                repo=str(draft_pr.get("repo") or ""),
                pr_url=str(url),
            )
