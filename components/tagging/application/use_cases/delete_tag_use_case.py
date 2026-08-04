"""Soft-delete a tag — non-destructive to assignments (D5); admin-gated at the API."""

from __future__ import annotations

import logging

from components.tagging.application.commands.delete_tag_command import DeleteTagCommand
from components.tagging.application.ports.tag_store_port import TagStorePort

logger = logging.getLogger(__name__)


class DeleteTagUseCase:
    def __init__(self, *, store: TagStorePort) -> None:
        self._store = store

    def execute(self, command: DeleteTagCommand) -> None:
        self._store.soft_delete(command.workspace_id, command.tag_id)
        logger.info(
            "tag_soft_deleted workspace_id=%s tag_id=%s actor_id=%s",
            command.workspace_id,
            command.tag_id,
            command.actor_id,
        )
