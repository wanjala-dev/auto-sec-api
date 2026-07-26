"""Sync the cloud asset graph from the inventory source — framework-free."""

from __future__ import annotations

from uuid import UUID

from components.cloud_graph.application.ports.asset_inventory_port import (
    AssetInventoryPort,
    AssetSyncResult,
)


class SyncCloudAssetsUseCase:
    """Materialize/refresh a workspace's cloud assets through the inventory port.

    The driving adapter (the ``cloud_graph.sync`` detector) calls this; the substrate
    (Prowler-derived today, CloudQuery later) is the injected port, not this caller."""

    def __init__(self, inventory: AssetInventoryPort):
        self._inventory = inventory

    def execute(self, workspace_id: UUID) -> AssetSyncResult:
        return self._inventory.sync_workspace(workspace_id)
