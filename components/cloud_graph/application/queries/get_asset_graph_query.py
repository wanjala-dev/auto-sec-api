"""Read-side query + view DTO for the cloud asset graph (CQRS read).

Feeds the HUD's Asset Graph panel: a capped set of asset nodes for a workspace
plus the typed edges among them. Node exposure + typed relations already make
attack-path-shaped structures visible (public node → role → admin policy) ahead
of the §6 materialized attack-path CTE (ADR 0005).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity

# A HUD graph stays readable in the low hundreds of nodes; the cap protects both
# the browser layout (elkjs) and the DB from an unbounded workspace.
DEFAULT_NODE_LIMIT = 200
MAX_NODE_LIMIT = 500


@dataclass(frozen=True)
class GetAssetGraphQuery:
    """Filters + window for one whole-graph read. Filters AND together on nodes."""

    workspace_id: UUID
    resource_type: str | None = None
    exposure: str | None = None  # Exposure.value — public | internal | private
    limit: int = DEFAULT_NODE_LIMIT


@dataclass(frozen=True)
class AssetGraphView:
    """A workspace's asset graph: the selected nodes + the edges among only those nodes."""

    nodes: list[CloudAssetEntity] = field(default_factory=list)
    edges: list[CloudAssetEdgeEntity] = field(default_factory=list)
    total_nodes: int = 0  # nodes returned (== len(nodes); the graph is node-capped, not paged)
