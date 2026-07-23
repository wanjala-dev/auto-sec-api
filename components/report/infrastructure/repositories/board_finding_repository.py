"""Adapter: read board findings for a report from ``project.Task``.

Implements :class:`FindingSourcePort`. A pentest-report finding is a ``Task``
whose ``source_type`` starts with one of the kind's prefixes (``ai.`` today).
Eager-loads the FKs the section builder + matrix read (``column``, ``team``) so
the assembler never fires per-finding queries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from django.db.models import Q

from components.report.application.ports.finding_source_port import FindingSourcePort

# The posture-report card is itself an ``ai.*`` task — never include a report's
# own summary card as a finding in another report.
_EXCLUDED_SOURCE_TYPES = ("ai.posture_report",)


class BoardFindingRepository(FindingSourcePort):
    def list_findings(
        self,
        *,
        workspace_id: str,
        source_type_prefixes: Sequence[str],
        source_types: Sequence[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 500,
    ) -> list[Mapping[str, Any]]:
        from infrastructure.persistence.project.models import Task

        prefix_q = Q()
        for prefix in source_type_prefixes or ("ai.",):
            prefix_q |= Q(source_type__startswith=prefix)

        qs = (
            Task.objects.filter(workspace_id=workspace_id)
            .filter(prefix_q)
            .exclude(source_type__in=_EXCLUDED_SOURCE_TYPES)
            .select_related("column", "team")
        )
        if source_types:
            qs = qs.filter(source_type__in=list(source_types))
        if since is not None:
            qs = qs.filter(created_at__gte=since)
        if until is not None:
            qs = qs.filter(created_at__lte=until)

        qs = qs.order_by("-created_at")[: max(1, int(limit))]

        return [
            {
                "id": str(task.id),
                "title": task.title,
                "description": task.description or "",
                "source_type": task.source_type,
                "status": task.status,
                "created_at": task.created_at,
                "metadata": task.metadata or {},
            }
            for task in qs
        ]
