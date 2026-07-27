"""Approve + execute a proposed response action — the human-gated mutation.

This is the ``irreversible`` step, so it is reached ONLY through the authenticated
REST endpoint (a human), never as an autonomous agent tool. Approval carries a
required justification (the anti-rubber-stamp gate the meaningful-oversight
research prescribes) and then runs the mutation through the cloud port. A
dry-run approval proves permissions without changing anything; a real approval
performs the revoke and records exactly what AWS reported (so the recorded
inverse can restore it verbatim).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from components.response.application.ports.cloud_response_port import CloudResponsePort
from components.response.application.ports.response_action_store_port import (
    ResponseActionStorePort,
)
from components.response.domain.entities.response_action_entity import ResponseActionExecution
from components.response.domain.errors import (
    IllegalTransitionError,
    ResponseActionError,
    ResponseActionNotFoundError,
)

logger = logging.getLogger(__name__)


class ApproveResponseActionUseCase:
    def __init__(self, *, store: ResponseActionStorePort, cloud_port: CloudResponsePort) -> None:
        self._store = store
        self._cloud = cloud_port

    def execute(
        self,
        *,
        action_id: UUID,
        workspace_id: UUID,
        approver_id: str,
        justification: str,
    ) -> ResponseActionExecution:
        if not (justification and justification.strip()):
            raise ResponseActionError(
                "approving a response action requires a justification — an "
                "irreversible cloud change is not one-click approved"
            )

        action = self._store.get(action_id, workspace_id=workspace_id)
        if action is None:
            raise ResponseActionNotFoundError(str(action_id))
        if not action.status.can_approve:
            raise IllegalTransitionError(str(action_id), action.status.value, "approve")

        now = datetime.now(UTC)
        # Move to EXECUTED first (records the human decision + justification), then
        # attach the cloud result; a cloud failure demotes it to FAILED.
        approved = action.approved(decided_by=approver_id, decided_at=now, justification=justification.strip())

        outcome = self._cloud.apply(approved.spec, workspace_id=str(workspace_id), dry_run=approved.dry_run)
        result = approved.with_execution_result(
            executed_at=now,
            detail=outcome.detail,
            failed=not outcome.ok,
            error=outcome.error,
        )
        saved = self._store.save(result)
        logger.info(
            "response_action_approved id=%s status=%s dry_run=%s performed=%s approver=%s",
            saved.id,
            saved.status.value,
            saved.dry_run,
            outcome.performed,
            approver_id,
        )
        return saved
