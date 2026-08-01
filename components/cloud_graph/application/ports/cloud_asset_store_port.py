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
    def count_by_exposure(self, workspace_id: UUID) -> dict[str, int]:
        """Non-deleted asset counts grouped by exposure, e.g. {'public': 7, 'internal': 21,
        'private': 172}. Index-backed aggregate — the Attack-Surface / Asset cards read it."""

    @abstractmethod
    def count_by_type(self, workspace_id: UUID, *, top: int = 8) -> list[tuple[str, int]]:
        """Top resource types by asset count, most first — the Asset-Inventory breakdown."""

    @abstractmethod
    def list_public_asset_urns(self, workspace_id: UUID) -> list[str]:
        """asset_urns of the workspace's PUBLIC (internet-exposed) assets — the attack-surface
        set, intersected with open critical/high findings by URN to find what actually matters."""

    @abstractmethod
    def list_edges_from(self, workspace_id: UUID, src_asset_id: UUID) -> list[CloudAssetEdgeEntity]:
        """Outgoing edges from an asset — the traversal primitive the CTE queries build on."""

    @abstractmethod
    def list_all_edges(self, workspace_id: UUID, *, limit: int = 2000) -> list[CloudAssetEdgeEntity]:
        """Every edge in the workspace (capped) — the whole-graph read the HUD renders,
        distinct from the per-node ``list_edges_from`` traversal primitive."""

    # ── Sample/demo data (ADR 0011) ───────────────────────────────────────────
    # Sample rows are written DIRECTLY (no sync, no events) and torn down by tag, so
    # demo data never mixes into real posture nor fires real side-effects.

    @abstractmethod
    def has_real_assets(self, workspace_id: UUID) -> bool:
        """True if the workspace has ANY non-sample cloud asset — the mutual-exclusivity
        guard that stops sample data seeding onto a live workspace (mirrors
        ``FindingStorePort.has_real_findings``)."""

    @abstractmethod
    def seed_sample_graph(
        self,
        workspace_id: UUID,
        assets: list[CloudAssetEntity],
        edges: list[CloudAssetEdgeEntity],
    ) -> tuple[int, int]:
        """Replace the workspace's sample graph atomically: clear existing
        ``is_sample=True`` assets (and, by cascade, their edges) FIRST, then insert the
        given tagged assets + edges. Idempotent — re-seeding yields the same set with no
        UNIQUE violation on ``(workspace, arn)``. Real rows are untouched. Returns
        ``(assets_created, edges_created)``. The caller supplies stable entity ids so the
        edges can reference the asset ids without a round-trip."""

    @abstractmethod
    def clear_sample_assets(self, workspace_id: UUID) -> int:
        """Delete all ``is_sample=True`` assets (and, by cascade, their edges) for the
        workspace. Returns the number of assets removed. Real rows are untouched."""
