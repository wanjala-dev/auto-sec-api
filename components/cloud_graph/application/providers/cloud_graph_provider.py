"""Composition root for the cloud_graph context — wires ports to adapters."""

from __future__ import annotations

from components.cloud_graph.application.ports.cloud_asset_store_port import CloudAssetStorePort


class CloudGraphProvider:
    @staticmethod
    def build_cloud_asset_store() -> CloudAssetStorePort:
        """The graph read/write store — the cloud_graph context's public data seam.

        The Prowler-derived sync adapter (next slice) writes through this; later the
        CTE attack-path queries and the ``query_asset_graph`` agent tool read through it.
        """
        from components.cloud_graph.infrastructure.repositories.django_cloud_graph_repository import (
            DjangoCloudGraphRepository,
        )

        return DjangoCloudGraphRepository()

    @staticmethod
    def build_asset_inventory():
        """The ingestion adapter (spike §5). Prowler/SSOT-derived today; a CloudQuery
        adapter can replace it here without touching the use case."""
        from components.cloud_graph.infrastructure.adapters.finding_derived_inventory_adapter import (
            FindingDerivedInventoryAdapter,
        )

        return FindingDerivedInventoryAdapter()

    @staticmethod
    def build_sync_cloud_assets_use_case():
        """The use case the ``cloud_graph.sync`` detector drives."""
        from components.cloud_graph.application.use_cases.sync_cloud_assets_use_case import (
            SyncCloudAssetsUseCase,
        )

        return SyncCloudAssetsUseCase(inventory=CloudGraphProvider.build_asset_inventory())
