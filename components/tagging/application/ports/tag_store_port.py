"""Port: the tag vocabulary store — THE seam other contexts consume (ADR 0015).

The ONLY way another context touches the vocabulary (Rule 3: importing another
context's ``application.ports`` + domain types is allowed; its infrastructure is
not). Durable references (workflow rule configs, saved views) MUST store
``tag_id``, never the slug — the slug is a display/API handle that a rename can
change (D5); the UUID is the identity.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from components.shared_kernel.domain.tagging import TagRef
from components.tagging.application.commands.create_tag_command import CreateTagCommand
from components.tagging.application.commands.update_tag_command import UpdateTagCommand
from components.tagging.domain.entities.tag_entity import TagEntity


class TagStorePort(ABC):
    @abstractmethod
    def get_or_create(self, workspace_id: UUID, raw: str, *, kind: str = "user") -> TagEntity:
        """Normalize ``raw`` (name or namespace:name) and return the live tag, creating a
        ``user`` tag if absent. Raises InvalidTagError / ReservedTagError / TagLimitExceededError."""

    @abstractmethod
    def resolve_slugs(self, workspace_id: UUID, slugs: Sequence[str]) -> dict[str, UUID]:
        """Map normalized slugs → live tag ids. Inputs are normalized before lookup;
        unknown (or un-normalizable) slugs are simply absent from the result."""

    @abstractmethod
    def refs_for_ids(self, workspace_id: UUID, tag_ids: Sequence[UUID]) -> tuple[TagRef, ...]:
        """The live tags among ``tag_ids`` as read refs, ordered by slug."""

    @abstractmethod
    def get_by_id(self, workspace_id: UUID, tag_id: UUID) -> TagEntity:
        """The tag by id (workspace-scoped, soft-deleted rows included — the entity
        carries ``is_deleted``). Raises TagNotFoundError."""

    @abstractmethod
    def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        namespace: str | None = None,
        q: str | None = None,
        with_usage: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[TagEntity], int]:
        """Live tags only, ordered by slug, with the total for the same filter.
        ``with_usage`` annotates each entity's ``usage_count`` (assignment edges)."""

    @abstractmethod
    def create(self, command: CreateTagCommand) -> TagEntity:
        """Create a tag. Raises InvalidTagError / DuplicateTagError /
        ReservedTagError / TagLimitExceededError."""

    @abstractmethod
    def update(self, command: UpdateTagCommand) -> TagEntity:
        """Rename (re-slugs) / recolor / describe; restore via ``is_deleted=False``.
        Raises TagNotFoundError / InvalidTagError / DuplicateTagError / ReservedTagError."""

    @abstractmethod
    def soft_delete(self, workspace_id: UUID, tag_id: UUID) -> None:
        """Soft-delete the tag (assignments retained — D5). Raises TagNotFoundError /
        ReservedTagError (system tags are platform-managed)."""
