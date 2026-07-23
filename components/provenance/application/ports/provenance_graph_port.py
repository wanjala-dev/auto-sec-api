"""Port for reading the provenance/access graph.

The application core talks to the graph only through this interface; the Django
ORM implementation lives in ``infrastructure/repositories``. All methods are
read-only and workspace-scoped — the graph observes, it never mutates a
vendor's permissions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from components.provenance.application.queries.graph_queries import (
    AccessReviewRow,
    HallTree,
    LeastPrivilegeGap,
    VendorBlastRadius,
)


class ProvenanceGraphPort(ABC):
    @abstractmethod
    def vendor_blast_radius(self, *, workspace_id: UUID, actor_id: UUID) -> VendorBlastRadius:
        """All grants (potential) + recent events (actual) for one actor."""

    @abstractmethod
    def access_review(self, *, workspace_id: UUID, resource_id: UUID) -> list[AccessReviewRow]:
        """Every actor with a grant on a resource, for the access-review table."""

    @abstractmethod
    def hall_tree(self, *, workspace_id: UUID, actor_id: UUID, since: datetime, max_depth: int = 3) -> HallTree:
        """The provenance drill-down: what an actor touched over a window."""

    @abstractmethod
    def least_privilege_gaps(self, *, workspace_id: UUID, unused_days: int = 30) -> list[LeastPrivilegeGap]:
        """Grants with no observed use in the window (unused-permission signal)."""
