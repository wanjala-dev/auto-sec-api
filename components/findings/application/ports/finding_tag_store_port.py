"""Port: the FindingTag join — tag assignments on findings (ADR 0015 D10).

The join is owned by the findings context (the association lives with the entity
it tags); the tag *vocabulary* is owned by the tagging context behind its
``TagStorePort``. This port covers only the edge: link/unlink/read — an edge, not
a record (removal is a hard delete; provenance is the audit log line).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from components.shared_kernel.domain.tagging import TagRef


class FindingTagStorePort(ABC):
    @abstractmethod
    def tag_ids_for_finding(self, workspace_id: UUID, finding_id: UUID) -> set[UUID]:
        """All tag ids currently linked to the finding (soft-deleted tags included —
        the edges persist through a vocabulary soft-delete, D5)."""

    @abstractmethod
    def add_tags(
        self,
        workspace_id: UUID,
        finding_id: UUID,
        tag_ids: Sequence[UUID],
        *,
        actor_id: str | None,
        source: str = "user",
    ) -> None:
        """Idempotently link tags to the finding (existing links are no-ops).
        ``source`` is the D8 provenance stamp (user | agent | rule | system)."""

    @abstractmethod
    def remove_tags(self, workspace_id: UUID, finding_id: UUID, tag_ids: Sequence[UUID]) -> None:
        """Unlink tags from the finding (hard delete of the edges; unknown links no-op)."""

    @abstractmethod
    def refs_for_finding(self, workspace_id: UUID, finding_id: UUID) -> tuple[TagRef, ...]:
        """The finding's LIVE tags as read refs, ordered by slug (the chip row)."""
