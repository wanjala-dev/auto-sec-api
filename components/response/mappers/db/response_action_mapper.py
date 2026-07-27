"""ORM ↔ domain mapper for ResponseActionExecution — mechanical translation only."""

from __future__ import annotations

from uuid import UUID

from components.response.domain.entities.response_action_entity import ResponseActionExecution
from components.response.domain.value_objects.execution_status import ExecutionStatus
from components.response.domain.value_objects.response_action_spec import ResponseActionSpec


def to_entity(row) -> ResponseActionExecution:
    return ResponseActionExecution(
        id=row.id,
        workspace_id=row.workspace_id,
        finding_fingerprint=row.finding_fingerprint,
        spec=ResponseActionSpec.from_dict(row.spec),
        inverse_spec=ResponseActionSpec.from_dict(row.inverse_spec),
        status=ExecutionStatus(row.status),
        dry_run=row.dry_run,
        requested_by=row.requested_by,
        requested_at=row.requested_at,
        justification=row.justification,
        decided_by=row.decided_by or None,
        decided_at=row.decided_at,
        executed_at=row.executed_at,
        execution_detail=dict(row.execution_detail or {}),
        rolled_back_at=row.rolled_back_at,
        rollback_detail=dict(row.rollback_detail or {}),
        error=row.error or None,
    )


def to_row_fields(entity: ResponseActionExecution) -> dict:
    """The persistable field map (everything except the PK + workspace FK, which
    the repository sets explicitly on create)."""
    return {
        "finding_fingerprint": entity.finding_fingerprint,
        "kind": entity.spec.kind.value,
        "spec": entity.spec.to_dict(),
        "inverse_spec": entity.inverse_spec.to_dict(),
        "status": entity.status.value,
        "dry_run": entity.dry_run,
        "requested_by": entity.requested_by or "",
        "requested_at": entity.requested_at,
        "justification": entity.justification or "",
        "decided_by": entity.decided_by or "",
        "decided_at": entity.decided_at,
        "executed_at": entity.executed_at,
        "execution_detail": entity.execution_detail or {},
        "rolled_back_at": entity.rolled_back_at,
        "rollback_detail": entity.rollback_detail or {},
        "error": entity.error or "",
    }


def coerce_uuid(value) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
