"""Reject a proposed response action — a human declines it. No cloud effect."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from components.response.application.ports.response_action_store_port import (
    ResponseActionStorePort,
)
from components.response.domain.entities.response_action_entity import ResponseActionExecution
from components.response.domain.errors import IllegalTransitionError, ResponseActionNotFoundError

logger = logging.getLogger(__name__)


class RejectResponseActionUseCase:
    def __init__(self, *, store: ResponseActionStorePort) -> None:
        self._store = store

    def execute(self, *, action_id: UUID, workspace_id: UUID, actor_id: str, note: str = "") -> ResponseActionExecution:
        action = self._store.get(action_id, workspace_id=workspace_id)
        if action is None:
            raise ResponseActionNotFoundError(str(action_id))
        if not action.status.can_reject:
            raise IllegalTransitionError(str(action_id), action.status.value, "reject")

        rejected = action.rejected(decided_by=actor_id, decided_at=datetime.now(UTC), note=note)
        saved = self._store.save(rejected)
        logger.info("response_action_rejected id=%s actor=%s", saved.id, actor_id)
        return saved
