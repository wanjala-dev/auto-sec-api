"""List a workspace's live tag vocabulary (CQRS read) — the tag-picker read (D6)."""

from __future__ import annotations

from uuid import UUID

from components.tagging.application.ports.tag_store_port import TagStorePort
from components.tagging.domain.entities.tag_entity import TagEntity


class ListTagsUseCase:
    def __init__(self, *, store: TagStorePort) -> None:
        self._store = store

    def execute(
        self,
        workspace_id: UUID,
        *,
        namespace: str | None = None,
        q: str | None = None,
        with_usage: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[TagEntity], int]:
        return self._store.list_for_workspace(
            workspace_id,
            namespace=namespace,
            q=q,
            with_usage=with_usage,
            limit=limit,
            offset=offset,
        )
