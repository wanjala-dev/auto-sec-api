"""Adapter: read report findings from the board (``project.Task``).

Implements :class:`FindingSourcePort` over the Kanban board: a finding is a
``Task`` whose ``source_type`` starts with one of the kind's board prefixes
(``ai.``). Eager-loads the FKs + assignees the enrichment reads, so the assembler
never fires a per-finding query.

**This is the board-only lens, and it is no longer the default.** It can only
ever see what the board's severity floor let through (ADR 0019 D4 files at
``high``) — every low/medium/informational finding, and every deliberately
SSOT-only source (ADR 0021 D4), is structurally invisible to it. The default
adapter is ``SsotFindingRepository``, which reads the Finding SSOT and joins this
same board state on as enrichment. Keep this one for a report kind that genuinely
means "what the board carried", and for nothing else.

Because the board has no finding lifecycle, its accounting is honest by
construction rather than by policy: there are no suppressed/resolved rows to
exclude, and a ``Task`` is on the board by definition, so every row enriches to
``on_board = True``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Q

from components.report.application.ports.finding_source_port import (
    FindingPage,
    FindingQuery,
    FindingSourcePort,
)

# The posture-report card is itself an ``ai.*`` task — never include a report's
# own summary card as a finding in another report. (The SSOT adapter needs no
# such exclusion: ``PostureReportDetector`` writes a board Task directly and
# never raises a Finding, so the card simply is not in the SSOT.)
_EXCLUDED_SOURCE_TYPES = ("ai.posture_report",)


class BoardFindingRepository(FindingSourcePort):
    def list_findings(self, query: FindingQuery) -> FindingPage:
        from infrastructure.persistence.project.models import Task

        prefix_q = Q()
        for prefix in query.source_prefixes or ("ai.",):
            prefix_q |= Q(source_type__startswith=prefix)

        qs = (
            Task.objects.filter(workspace_id=query.workspace_id)
            .filter(prefix_q)
            .exclude(source_type__in=_EXCLUDED_SOURCE_TYPES)
            .select_related("column", "team")
            .prefetch_related("assigned_to")
        )
        if query.sources:
            qs = qs.filter(source_type__in=list(query.sources))
        # A board card has no observation window — ``created_at`` is when the card
        # appeared, which is the best this source can honestly answer.
        if query.since is not None:
            qs = qs.filter(created_at__gte=query.since)
        if query.until is not None:
            qs = qs.filter(created_at__lte=query.until)

        total_matched = qs.count()
        rows = list(qs.order_by("-created_at")[: max(1, int(query.limit))])

        return FindingPage(
            findings=tuple(self._to_mapping(task) for task in rows),
            total_matched=total_matched,
        )

    @staticmethod
    def _to_mapping(task) -> Mapping[str, Any]:
        metadata = task.metadata or {}
        return {
            "id": str(task.id),
            "title": task.title,
            "description": task.description or "",
            # Hoisted to first class: the port's contract is that severity is a
            # top-level fact, not something every consumer digs out of metadata.
            "severity": str(metadata.get("severity") or ""),
            "status": task.status,
            "source": task.source_type or "",
            "source_type": task.source_type or "",
            "created_at": task.created_at,
            "first_seen_at": task.created_at,
            "last_seen_at": task.created_at,
            "resolved_at": None,
            "is_sample": False,
            "metadata": metadata,
            "triage": {
                "on_board": True,
                "task_id": str(task.id),
                "source_type": task.source_type or "",
                "column": (task.column.title if task.column else ""),
                "team": (task.team.title if task.team else ""),
                "task_status": task.status or "",
                "triage_status": str((metadata.get("triage") or {}).get("status") or ""),
                "assignees": sorted((user.username or user.email or "") for user in task.assigned_to.all()),
            },
        }
