"""Real audit adapter: writes recycle-bin lifecycle events to the
shared ``EntityAuditLog`` table.

The recycle bin used to ship with a ``NullAuditLogAdapter`` that
only emitted Python log lines. That was fine while the bin was an
internal-only feature, but the moment it became user-facing (and
load-bearing for "who deleted my budget?" investigations) we needed
durable, queryable history.

Mapping to ``EntityAuditLog``:

    field_name      = "deletion_stage"   (consistent across every recycle-bin event)
    previous_value  = the stage we left  (e.g. "active", "trashed")
    new_value       = the stage we entered (e.g. "trashed", "active", "purged")
    actor_id        = the user who acted (UUID stringified)
    reason          = the human-readable justification from the UI

Reads are free because the existing
``GET /audit/entries/?entity_type=<x>&object_id=<id>`` endpoint
already paginates this table — no new read API needed.
"""
from __future__ import annotations

import logging
from uuid import UUID

from components.audit.application.ports.audit_log_port import (
    AuditLogPort as SharedAuditLogPort,
)
from components.recycle_bin.application.ports.audit_log_port import (
    AuditLogPort,
)

logger = logging.getLogger(__name__)


_FIELD_NAME = "deletion_stage"


class EntityAuditLogAuditAdapter(AuditLogPort):
    """Wraps the shared ``EntityAuditLogRepository`` and adapts its
    ``record(...)`` shape onto the three verbs the recycle bin needs.
    """

    def __init__(self, shared_audit_log: SharedAuditLogPort) -> None:
        self._shared = shared_audit_log

    def log_trash(
        self,
        *,
        entity_type: str,
        entity_id: str,
        workspace_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> None:
        self._record(
            entity_type=entity_type,
            entity_id=entity_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            previous_value="active",
            new_value="trashed",
            reason=reason,
        )

    def log_restore(
        self,
        *,
        entity_type: str,
        entity_id: str,
        workspace_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> None:
        self._record(
            entity_type=entity_type,
            entity_id=entity_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            previous_value="trashed",
            new_value="active",
            reason=reason,
        )

    def log_purge(
        self,
        *,
        entity_type: str,
        entity_id: str,
        workspace_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> None:
        self._record(
            entity_type=entity_type,
            entity_id=entity_id,
            workspace_id=workspace_id,
            actor_id=actor_id,
            previous_value="trashed",
            new_value="purged",
            reason=reason,
        )

    def _record(
        self,
        *,
        entity_type: str,
        entity_id: str,
        workspace_id: UUID,
        actor_id: UUID,
        previous_value: str,
        new_value: str,
        reason: str,
    ) -> None:
        try:
            self._shared.record(
                workspace_id=str(workspace_id),
                entity_type=entity_type,
                entity_id=str(entity_id),
                field_name=_FIELD_NAME,
                previous_value=previous_value,
                new_value=new_value,
                actor_id=str(actor_id) if actor_id is not None else None,
                reason=reason or "",
            )
        except Exception:
            # Audit failure must NEVER fail the user-facing action.
            # Log loudly so monitoring can pick it up, then return —
            # the trash/restore/purge themselves are already committed.
            logger.exception(
                "recycle_bin_audit_write_failed entity_type=%s entity_id=%s "
                "actor_id=%s transition=%s->%s",
                entity_type,
                entity_id,
                actor_id,
                previous_value,
                new_value,
            )
