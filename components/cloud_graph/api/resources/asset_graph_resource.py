"""Output DTO for the asset-graph read API — a JSON-safe {nodes, edges} graph."""

from __future__ import annotations

from components.cloud_graph.application.queries.get_asset_graph_query import AssetGraphView
from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity


class AssetGraphResource:
    @staticmethod
    def _node(a: CloudAssetEntity) -> dict:
        attrs = a.attributes or {}
        return {
            "id": str(a.id),
            "arn": a.arn,
            "asset_urn": a.asset_urn,
            "resource_type": a.resource_type,
            "exposure": a.exposure.value,
            "is_public": a.is_public,
            "region": a.region,
            "name": a.name or a.arn.rsplit("/", 1)[-1] or a.resource_type,
            "account_id": attrs.get("account_id", ""),
            "service": attrs.get("service", ""),
        }

    @staticmethod
    def _edge(e: CloudAssetEdgeEntity) -> dict:
        # source/target follow the ReactFlow convention the HUD renders with.
        return {
            "id": str(e.id),
            "source": str(e.src_asset_id),
            "target": str(e.dst_asset_id),
            "relation": e.relation.value,
        }

    @staticmethod
    def graph(view: AssetGraphView) -> dict:
        return {
            "nodes": [AssetGraphResource._node(a) for a in view.nodes],
            "edges": [AssetGraphResource._edge(e) for e in view.edges],
            "total_nodes": view.total_nodes,
        }
