"""Adapter: read board-finding posture facts from ``project.Task``.

Implements :class:`PostureFactsPort`. The ``project`` context reading its OWN
persistence model behind its own application port — the sanctioned inbound read
seam the ``agents`` posture services consume, mirroring
``BoardFindingFactsRepository`` in ``remediation``.

Both reads are workspace-scoped (tenant isolation) and exclude the posture
report's own board card so the weekly report can never count (or inflate)
itself. The finding-facts read reproduces ``posture_service._collect_finding_rows``
exactly: two querysets (open cards ∪ window-touched cards) deduped by id, each
row shaped into a :class:`PostureFinding` DTO by ``_to_finding`` (the ORM-side
mirror of ``posture_service._finding_row``).
"""

from __future__ import annotations

from datetime import datetime

from components.project.application.ports.posture_facts_port import (
    PostureFactsPort,
    PostureFinding,
)

# The posture report's own board card. Kept out of every posture aggregate so
# the weekly report can never count itself. Same value as
# ``posture_service.POSTURE_REPORT_SOURCE_TYPE`` — duplicated (not imported) so
# this ``project`` adapter takes no dependency on the ``agents`` context that
# consumes it; the value is a shared source-type convention, not agents-owned
# behaviour.
_POSTURE_REPORT_SOURCE_TYPE = "ai.posture_report"


def _to_finding(task) -> PostureFinding:
    """Shape one ``Task`` into the posture DTO (mirrors ``_finding_row``)."""
    meta = task.metadata or {}
    triage = meta.get("triage") or {}
    telemetry = meta.get("run_telemetry") if isinstance(meta.get("run_telemetry"), dict) else {}
    rubric = telemetry.get("rubric_verdicts") if isinstance(telemetry.get("rubric_verdicts"), dict) else None

    # Acknowledgment proxy: the first provenance event AFTER the filing event
    # (an agent/human acted on the card). Filing itself is not an ack.
    first_action_at = None
    events = ((meta.get("provenance") or {}).get("events") or [])[1:]
    if events and isinstance(events[0], dict):
        first_action_at = events[0].get("at")

    return PostureFinding(
        id=str(task.id),
        severity=meta.get("severity") or "",
        kind=task.source_type,
        status=task.status,
        created_at=task.created_at,
        triage_status=triage.get("status"),
        triaged_at=triage.get("triaged_at"),
        needs_human=bool(triage.get("needs_human")),
        agent=triage.get("agent") or "",
        rubric_verdict=rubric.get("verdict") if rubric else None,
        first_action_at=first_action_at,
    )


class OrmPostureFactsRepository(PostureFactsPort):
    def collect_finding_facts(self, *, workspace_id: str, window_start: datetime) -> list[PostureFinding]:
        from infrastructure.persistence.project.models import Task

        base = (
            Task.objects.filter(workspace_id=str(workspace_id), source_type__startswith="ai.")
            .exclude(source_type=_POSTURE_REPORT_SOURCE_TYPE)
            .only("id", "status", "source_type", "created_at", "metadata")
        )
        rows: dict[str, PostureFinding] = {}
        for queryset in (base.filter(status="todo"), base.filter(updated_at__gte=window_start)):
            for task in queryset.iterator(chunk_size=500):
                finding = _to_finding(task)
                rows[finding.id] = finding
        return list(rows.values())

    def count_findings_created(self, *, workspace_id: str, since: datetime, until: datetime | None = None) -> int:
        from infrastructure.persistence.project.models import Task

        queryset = Task.objects.filter(
            workspace_id=str(workspace_id),
            source_type__startswith="ai.",
            created_at__gte=since,
        ).exclude(source_type=_POSTURE_REPORT_SOURCE_TYPE)
        if until is not None:
            queryset = queryset.filter(created_at__lt=until)
        return queryset.count()

    def count_findings_created_by_date(self, *, workspace_id: str, since: datetime) -> tuple[dict[str, int], bool]:
        from infrastructure.persistence.project.models import Task

        created_rows = (
            Task.objects.filter(
                workspace_id=str(workspace_id),
                source_type__startswith="ai.",
                created_at__gte=since,
            )
            .exclude(source_type=_POSTURE_REPORT_SOURCE_TYPE)
            .values_list("created_at", flat=True)
            .iterator(chunk_size=500)
        )
        by_date: dict[str, int] = {}
        present = False
        for created_at in created_rows:
            present = True
            iso = created_at.date().isoformat()
            by_date[iso] = by_date.get(iso, 0) + 1
        return by_date, present
