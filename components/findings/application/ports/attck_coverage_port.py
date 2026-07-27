"""Port: read the raw ATT&CK tags off open findings + persist/read the materialized heatmap."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class CoverageSnapshot:
    """The materialized heatmap row (or an empty default when never computed)."""

    coverage: dict
    technique_count: int
    finding_count: int
    computed_at: datetime | None

    @property
    def is_materialized(self) -> bool:
        return self.computed_at is not None


class AttckCoverageStorePort(ABC):
    @abstractmethod
    def open_finding_attck_tags(self, workspace_id: UUID) -> list[tuple[list[str], str]]:
        """Every open finding's ``(technique_ids, severity)`` — the aggregation input."""

    @abstractmethod
    def save(
        self, workspace_id: UUID, *, coverage: dict, technique_count: int, finding_count: int, computed_at: datetime
    ) -> None:
        """Overwrite the workspace's materialized coverage row."""

    @abstractmethod
    def get(self, workspace_id: UUID) -> CoverageSnapshot:
        """The materialized row, or an empty snapshot (``computed_at=None``) if absent."""
