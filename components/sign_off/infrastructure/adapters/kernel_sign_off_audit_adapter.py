"""Queue-level audit sink for sign-off decisions.

Implements the kernel's :class:`SignOffAuditPort` by writing every queue
decision (approved / changes-requested / rejected) to the shared, append-only
``EntityAuditLog`` — the same table the recycle bin, field-edit history, and the
reports sign-off audit already use (reused, not forked — the "one ledger" rule).

Rows are recorded under ``entity_type = "signoff.<artifact_type>"``, which is
DISTINCT from any context's own field-history entity_type (e.g. the reports
context audits under ``reports.financialreport``). So this is a complementary
queue-decision trail, not a duplicate of a context's own audit.

The artifact's workspace is resolved through the sign-off registry adapter
(``adapter.workspace_id``) — the kernel never touches a foreign context's ORM
directly. An audit write must NEVER fail the user-facing decision, so failures
are logged loudly and swallowed (same contract the recycle-bin + reports audit
adapters use).
"""

from __future__ import annotations

import logging

from components.sign_off.application.ports.sign_off_audit_port import SignOffAuditPort
from components.sign_off.application.providers.sign_off_registry_provider import (
    get_sign_off_registry,
)

logger = logging.getLogger(__name__)

_FIELD_NAME = "review_state"


class KernelSignOffAuditAdapter(SignOffAuditPort):
    def __init__(self, audit_repository=None) -> None:
        self._repo = audit_repository

    def record(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        event: str,
        actor_id: str | None,
        detail: dict | None = None,
    ) -> None:
        detail = detail or {}
        try:
            reason = detail.get("override_reason") or detail.get("note") or ""
            self._repository().record(
                workspace_id=self._workspace_id(artifact_type, artifact_id),
                entity_type=f"signoff.{artifact_type}",
                entity_id=str(artifact_id),
                field_name=_FIELD_NAME,
                previous_value=None,
                new_value=event,
                actor_id=str(actor_id) if actor_id is not None else None,
                reason=reason,
            )
        except Exception:
            # Audit failure must never break the sign-off decision itself.
            logger.exception(
                "sign_off.queue_audit_write_failed artifact_type=%s artifact_id=%s event=%s",
                artifact_type,
                artifact_id,
                event,
            )

    def _repository(self):
        if self._repo is None:
            from components.audit.application.providers.entity_audit_log_repository_provider import (
                get_entity_audit_log_repository_provider,
            )

            self._repo = get_entity_audit_log_repository_provider().repository()
        return self._repo

    @staticmethod
    def _workspace_id(artifact_type: str, artifact_id: str) -> str | None:
        adapter = get_sign_off_registry().get_adapter(artifact_type)
        return adapter.workspace_id(str(artifact_id))
