"""Port: fill the asset graph from a cloud inventory source (the ingestion seam).

Shaped to the core's need — ``sync_workspace`` — so the adapter can be swapped without
touching the caller (architecture-manifesto Rule 5): the Prowler/SSOT-derived adapter
today, a CloudQuery adapter for a complete inventory later (spike §3/§5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AssetSyncResult:
    workspace_id: UUID
    assets_upserted: int = 0
    findings_scanned: int = 0


class AssetInventoryPort(ABC):
    @abstractmethod
    def sync_workspace(self, workspace_id: UUID) -> AssetSyncResult:
        """Materialize/refresh the workspace's cloud assets from the inventory source.

        Idempotent — a re-sync updates existing assets in place (no duplicates)."""
