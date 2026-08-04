"""Create a tag in the workspace vocabulary — framework-free orchestration (D6)."""

from __future__ import annotations

import logging

from components.tagging.application.commands.create_tag_command import CreateTagCommand
from components.tagging.application.ports.tag_store_port import TagStorePort
from components.tagging.domain.entities.tag_entity import TagEntity

logger = logging.getLogger(__name__)


class CreateTagUseCase:
    def __init__(self, *, store: TagStorePort) -> None:
        self._store = store

    def execute(self, command: CreateTagCommand) -> TagEntity:
        tag = self._store.create(command)
        logger.info(
            "tag_created workspace_id=%s tag_id=%s slug=%s actor_id=%s",
            command.workspace_id,
            tag.id,
            tag.slug,
            command.actor_id,
        )
        return tag
