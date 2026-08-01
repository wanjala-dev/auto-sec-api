"""Port: persistence of materialised attack paths, shaped to the core's needs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.cloud_graph.domain.entities.attack_path_entity import AttackPathEntity


class AttackPathStorePort(ABC):
    @abstractmethod
    def replace_for_workspace(self, workspace_id: UUID, paths: list[AttackPathEntity]) -> int:
        """Full recompute: atomically drop the workspace's existing paths and store the
        new set. Returns the number persisted. Idempotent — the materialisation job owns
        the whole set, so replace rather than merge."""

    @abstractmethod
    def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        category: str | None = None,
        min_score: float | None = None,
        limit: int = 50,
    ) -> list[AttackPathEntity]:
        """Ranked read (highest risk first), workspace-scoped, optionally filtered."""

    # ── Sample/demo data (ADR 0011) ───────────────────────────────────────────

    @abstractmethod
    def seed_sample_paths(self, workspace_id: UUID, paths: list[AttackPathEntity]) -> int:
        """Insert tagged (``is_sample=True``) demo paths directly — NOT via the
        materialize detector (no graph read, no events). First clears any existing sample
        paths so re-seeding is idempotent; real paths are untouched. Returns the count."""

    @abstractmethod
    def clear_sample_paths(self, workspace_id: UUID) -> int:
        """Delete the workspace's ``is_sample=True`` attack paths. Real paths untouched."""
