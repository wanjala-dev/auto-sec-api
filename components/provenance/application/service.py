"""Application front door for the provenance/access graph read surface.

Thin orchestration over :class:`ProvenanceGraphPort` — the controller talks to
this, never to the repository directly. Read-only; workspace-scoped.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from components.provenance.application.ports.provenance_graph_port import ProvenanceGraphPort
from components.provenance.application.queries.provenance_graph_query import (
    AccessReviewRow,
    HallTree,
    LeastPrivilegeGap,
    VendorBlastRadius,
)


class ProvenanceService:
    def __init__(self, graph: ProvenanceGraphPort):
        self._graph = graph

    def vendor_blast_radius(self, *, workspace_id: UUID, actor_id: UUID) -> VendorBlastRadius | None:
        return self._graph.vendor_blast_radius(workspace_id=workspace_id, actor_id=actor_id)

    def access_review(self, *, workspace_id: UUID, resource_id: UUID) -> list[AccessReviewRow]:
        return self._graph.access_review(workspace_id=workspace_id, resource_id=resource_id)

    def hall_tree(self, *, workspace_id: UUID, actor_id: UUID, since: datetime, max_depth: int = 3) -> HallTree | None:
        return self._graph.hall_tree(workspace_id=workspace_id, actor_id=actor_id, since=since, max_depth=max_depth)

    def least_privilege_gaps(self, *, workspace_id: UUID, unused_days: int = 30) -> list[LeastPrivilegeGap]:
        return self._graph.least_privilege_gaps(workspace_id=workspace_id, unused_days=unused_days)
