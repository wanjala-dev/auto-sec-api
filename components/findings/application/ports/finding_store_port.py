"""Port: persistence of the Finding SSOT, shaped to the application core's needs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.findings.domain.entities.finding_entity import FindingEntity


class FindingStorePort(ABC):
    @abstractmethod
    def find_by_identity(self, workspace_id: UUID, source: str, fingerprint: str) -> FindingEntity | None:
        """Return the finding for the dedup identity (workspace, source, fingerprint), or None."""

    @abstractmethod
    def find_by_id(self, workspace_id: UUID, finding_id: UUID) -> FindingEntity | None:
        """Return the finding by its id (workspace-scoped), or None. Read side."""

    @abstractmethod
    def upsert(self, finding: FindingEntity) -> None:
        """Insert or update the finding, keyed by its (workspace, source, fingerprint) identity."""
