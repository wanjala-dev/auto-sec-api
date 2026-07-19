"""Logger-only audit adapter — kept for tests and management-command
contexts where the shared ``EntityAuditLog`` repository isn't worth
wiring up.

Production uses ``EntityAuditLogAuditAdapter`` (writes to the shared
audit table); this is the fallback the unit tests inject via the
in-memory bin fakes.
"""
from __future__ import annotations

import logging
from uuid import UUID

from components.recycle_bin.application.ports.audit_log_port import AuditLogPort

logger = logging.getLogger(__name__)


class NullAuditLogAdapter(AuditLogPort):
    """No-op audit adapter — emits a Python log line per call."""

    def log_trash(
        self,
        *,
        entity_type: str,
        entity_id: str,
        workspace_id: UUID,
        actor_id: UUID,
        reason: str,
    ) -> None:
        logger.info(
            "AUDIT: trashed entity_type=%s entity_id=%s workspace_id=%s actor=%s reason=%r",
            entity_type, entity_id, workspace_id, actor_id, reason,
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
        logger.info(
            "AUDIT: restored entity_type=%s entity_id=%s workspace_id=%s actor=%s reason=%r",
            entity_type, entity_id, workspace_id, actor_id, reason,
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
        logger.info(
            "AUDIT: purged entity_type=%s entity_id=%s workspace_id=%s actor=%s reason=%r",
            entity_type, entity_id, workspace_id, actor_id, reason,
        )
