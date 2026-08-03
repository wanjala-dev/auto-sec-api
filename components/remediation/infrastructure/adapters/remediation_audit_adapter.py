"""Adapter: record a corpus revocation in the shared audit log (ADR 0012 P5).

Implements :class:`RemediationAuditPort` by delegating to the ``audit`` context's
application surface (``AuditLogPort.record`` via the audit repository provider) — an
id-based write, so it NEVER imports the RemediationEntry ORM model (which would
break the sole-writer invariant, D1). The revocation is mapped onto one immutable
``EntityAuditLog`` row:

    entity_type    = "remediation.remediationentry"  (app_label.model — resolves the
                     ContentType; a bare name would not match "remediationentry")
    entity_id      = the revoked entry's id
    field_name     = "corpus_membership"
    previous_value = "active"
    new_value      = "revoked"
    actor_id       = who revoked it
    reason         = the human-readable justification

Best-effort: an audit-write failure is logged, never raised — the revocation is
already committed, and a governance action must not be undone by an audit hiccup
(the same posture the recycle-bin audit adapter takes).
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.remediation.application.ports.remediation_audit_port import (
    RemediationAuditPort,
)

logger = logging.getLogger(__name__)

_ENTITY_TYPE = "remediation.remediationentry"
_FIELD_NAME = "corpus_membership"


class RemediationAuditAdapter(RemediationAuditPort):
    def __init__(self, shared_audit_log=None) -> None:
        # ``shared_audit_log`` is the audit context's ``AuditLogPort``; tests inject a
        # fake, production resolves the real repository through audit's provider.
        self._shared = shared_audit_log

    def _audit_log(self):
        if self._shared is not None:
            return self._shared
        from components.audit.application.providers.entity_audit_log_repository_provider import (
            get_entity_audit_log_repository_provider,
        )

        self._shared = get_entity_audit_log_repository_provider().repository()
        return self._shared

    def log_revocation(
        self,
        *,
        entry_id: UUID,
        workspace_id: UUID,
        actor_id: str | None,
        reason: str,
    ) -> None:
        try:
            self._audit_log().record(
                workspace_id=str(workspace_id),
                entity_type=_ENTITY_TYPE,
                entity_id=str(entry_id),
                field_name=_FIELD_NAME,
                previous_value="active",
                new_value="revoked",
                actor_id=str(actor_id) if actor_id is not None else None,
                reason=reason or "",
            )
        except Exception:
            # Audit failure must NEVER fail the governance action (already committed).
            logger.exception(
                "remediation_revocation_audit_failed entry_id=%s workspace_id=%s actor_id=%s",
                entry_id,
                workspace_id,
                actor_id,
            )
