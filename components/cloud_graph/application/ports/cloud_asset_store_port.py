"""Port: persistence of the cloud asset graph, shaped to the core's needs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity


class CloudAssetStorePort(ABC):
    @abstractmethod
    def upsert_asset(self, asset: CloudAssetEntity) -> CloudAssetEntity:
        """Insert or update by ``(workspace, arn)`` identity. Idempotent: a re-sync
        updates ``last_seen`` + config on the existing row and preserves ``first_seen``.
        Returns the persisted entity (with its stable id)."""

    @abstractmethod
    def upsert_edge(self, edge: CloudAssetEdgeEntity) -> CloudAssetEdgeEntity:
        """Insert or update by ``(src, dst, relation)`` identity. Idempotent."""

    @abstractmethod
    def get_asset_by_arn(self, workspace_id: UUID, arn: str) -> CloudAssetEntity | None:
        """Return the asset for the identity, or None. Read side."""

    @abstractmethod
    def list_assets(
        self,
        workspace_id: UUID,
        *,
        resource_type: str | None = None,
        exposure: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CloudAssetEntity]:
        """Filtered, paginated, workspace-scoped asset list (most-recently-seen first)."""

    @abstractmethod
    def list_edges_from(self, workspace_id: UUID, src_asset_id: UUID) -> list[CloudAssetEdgeEntity]:
        """Outgoing edges from an asset — the traversal primitive the CTE queries build on."""
