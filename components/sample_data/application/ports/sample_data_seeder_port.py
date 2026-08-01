"""Port: a per-context sample/demo-data seeder (ADR 0011 Phase 2).

The ``sample_data`` context owns this interface; each OTHER context (findings,
cloud_graph, …) implements it for ITS own data and registers the implementation
with the coordinator's composition root. The ``SampleDataFacade`` fans out across
every registered seeder so demo mode seeds/tears down many contexts as one set —
without any context importing another's infrastructure.

Every implementation MUST write DIRECTLY (bypassing domain events / real pipelines)
so sample data never fires a real outbound side-effect, and MUST tear itself down by
its own tag so a workspace going live carries no orphan demo rows (ADR 0011 D4).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID


class SampleDataSeederPort(ABC):
    @property
    @abstractmethod
    def context(self) -> str:
        """Short identifier of the context this seeder covers (e.g. ``"findings"``,
        ``"cloud_graph"``) — used in the aggregate result so the facade can report
        completeness per context."""

    @abstractmethod
    def seed(self, workspace_id: UUID, *, now: datetime) -> dict:
        """Seed this context's coherent sample rows for the workspace. Idempotent and
        guarded: skip if the workspace already holds REAL data for this context (the
        mutual-exclusivity guard). Returns a small result dict (e.g.
        ``{"seeded": 6, "skipped": False}``)."""

    @abstractmethod
    def clear(self, workspace_id: UUID) -> dict:
        """Remove ONLY this context's sample rows for the workspace (delete-by-tag).
        Returns a small result dict (e.g. ``{"deleted": 6}``)."""
