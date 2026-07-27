"""Roll back an executed response action — run its inverse, restoring prior state.

This is what makes the action *reversible*: the inverse spec (computed and stored
at propose time) is applied through the same cloud port, re-authorizing the exact
rule that was revoked. A rollback inherits the original's dry-run flag, so undoing
a dry-run is itself a no-op dry-run (symmetry), and undoing a real revoke really
re-opens the rule.
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


class RollbackResponseActionUseCase:
    def __init__(self, *, store: ResponseActionStorePort, cloud_port: CloudResponsePort) -> None:
        self._store = store
        self._cloud = cloud_port

    def execute(self, *, action_id: UUID, workspace_id: UUID, actor_id: str) -> ResponseActionExecution:
        action = self._store.get(action_id, workspace_id=workspace_id)
        if action is None:
            raise ResponseActionNotFoundError(str(action_id))
        if not action.status.can_rollback:
            raise IllegalTransitionError(str(action_id), action.status.value, "rollback")

        outcome = self._cloud.apply(action.inverse_spec, workspace_id=str(workspace_id), dry_run=action.dry_run)
        if not outcome.ok:
            # A failed rollback leaves the action EXECUTED (still reversible — the
            # operator can retry); we surface the error rather than lie about state.
            raise ResponseActionError(
                f"rollback of {action_id} failed: {outcome.error or 'cloud call did not succeed'}"
            )

        rolled = action.rolled_back(rolled_back_at=datetime.now(UTC), detail=outcome.detail)
        saved = self._store.save(rolled)
        logger.info(
            "response_action_rolled_back id=%s dry_run=%s performed=%s actor=%s",
            saved.id,
            saved.dry_run,
            outcome.performed,
            actor_id,
        )
        return saved
