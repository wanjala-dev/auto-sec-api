"""Use case: assemble a workspace's asset graph view (nodes + edges among them)."""

from __future__ import annotations

from components.cloud_graph.application.ports.cloud_asset_store_port import CloudAssetStorePort
from components.cloud_graph.application.queries.get_asset_graph_query import (
    AssetGraphView,
    GetAssetGraphQuery,
)


class GetAssetGraphUseCase:
    def __init__(self, store: CloudAssetStorePort):
        self._store = store

    def execute(self, query: GetAssetGraphQuery) -> AssetGraphView:
        nodes = self._store.list_assets(
            query.workspace_id,
            resource_type=query.resource_type,
            exposure=query.exposure,
            limit=query.limit,
        )
        node_ids = {n.id for n in nodes}
        # Only edges whose BOTH endpoints are in the returned (capped/filtered) node
        # set — a dangling edge would make the client's elkjs layout throw.
        edges = [
            e
            for e in self._store.list_all_edges(query.workspace_id)
            if e.src_asset_id in node_ids and e.dst_asset_id in node_ids
        ]
        return AssetGraphView(nodes=nodes, edges=edges, total_nodes=len(nodes))
