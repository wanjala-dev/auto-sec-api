"""ORM ↔ domain mapper for RemediationEntry — mechanical translation only."""

from __future__ import annotations

from components.remediation.domain.entities.remediation_entry_entity import RemediationEntry


def to_entity(row) -> RemediationEntry:
    return RemediationEntry(
        id=row.id,
        workspace_id=row.workspace_id,
        finding_kind=row.finding_kind,
        source_type=row.source_type or "",
        tags=tuple(row.tags or ()),
        language=row.language or "",
        code=row.code,
        title=row.title or "",
        summary=row.summary or "",
        finding_task_id=row.finding_task_id,
        finding_fingerprint=row.finding_fingerprint or "",
        provenance_event_ref=row.provenance_event_ref or "",
        applied_pr_url=row.applied_pr_url,
        approved_by=row.approved_by,
        resolved_at=row.resolved_at,
        reuse_count=row.reuse_count,
        success_count=row.success_count,
        recurrence_count=row.recurrence_count,
        last_outcome_at=row.last_outcome_at,
        score=row.score,
        embedded_at=row.embedded_at,
        created_at=row.created_at,
        is_deleted=row.is_deleted,
    )


def to_row_fields(entity: RemediationEntry) -> dict:
    """The persistable field map (everything except the PK + workspace FK, which
    the repository sets explicitly on create)."""
    return {
        "finding_kind": entity.finding_kind,
        "source_type": entity.source_type or "",
        "tags": list(entity.tags),
        "language": entity.language or "",
        "code": entity.code,
        "title": entity.title or "",
        "summary": entity.summary or "",
        "finding_task_id": entity.finding_task_id,
        "finding_fingerprint": entity.finding_fingerprint or "",
        "provenance_event_ref": entity.provenance_event_ref or "",
        "applied_pr_url": entity.applied_pr_url,
        "approved_by": entity.approved_by,
        "resolved_at": entity.resolved_at,
        "reuse_count": entity.reuse_count,
        "success_count": entity.success_count,
        "recurrence_count": entity.recurrence_count,
        "last_outcome_at": entity.last_outcome_at,
        "score": entity.score,
        "is_deleted": entity.is_deleted,
    }
