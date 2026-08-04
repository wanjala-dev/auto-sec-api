"""Rename (re-slug) / recolor / describe / restore a tag — admin-gated at the API (D5)."""

from __future__ import annotations

import logging

from components.tagging.application.commands.update_tag_command import UpdateTagCommand
from components.tagging.application.ports.tag_store_port import TagStorePort
from components.tagging.domain.entities.tag_entity import TagEntity

logger = logging.getLogger(__name__)


class UpdateTagUseCase:
    def __init__(self, *, store: TagStorePort) -> None:
        self._store = store

    def execute(self, command: UpdateTagCommand) -> TagEntity:
        tag = self._store.update(command)
        logger.info(
            "tag_updated workspace_id=%s tag_id=%s slug=%s is_deleted=%s actor_id=%s",
            command.workspace_id,
            tag.id,
            tag.slug,
            tag.is_deleted,
            command.actor_id,
        )
        return tag
