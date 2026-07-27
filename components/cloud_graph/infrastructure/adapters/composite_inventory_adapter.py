"""CompositeInventoryAdapter — run several ``AssetInventoryPort`` sources into one graph.

The finding-derived adapter gives node BREADTH (every resource any Prowler finding names);
the boto3 adapter gives relationship DEPTH (typed edges → attack paths). Both upsert
idempotently by ARN, so overlapping resources (an EC2 instance seen by both) merge on the
shared ARN rather than duplicating. A source that raises is logged and skipped — one bad
source never blanks the graph.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.cloud_graph.application.ports.asset_inventory_port import AssetInventoryPort, AssetSyncResult

logger = logging.getLogger(__name__)


class CompositeInventoryAdapter(AssetInventoryPort):
    def __init__(self, adapters: list[AssetInventoryPort]):
        self._adapters = adapters

    def sync_workspace(self, workspace_id: UUID) -> AssetSyncResult:
        assets = edges = findings = 0
        for adapter in self._adapters:
            try:
                result = adapter.sync_workspace(workspace_id)
                assets += result.assets_upserted
                edges += result.edges_upserted
                findings += result.findings_scanned
            except Exception:
                logger.exception(
                    "composite_inventory source failed workspace=%s adapter=%s",
                    workspace_id,
                    type(adapter).__name__,
                )
        return AssetSyncResult(
            workspace_id=workspace_id, assets_upserted=assets, findings_scanned=findings, edges_upserted=edges
        )
