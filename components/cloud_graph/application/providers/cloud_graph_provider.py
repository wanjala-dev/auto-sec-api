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
        """The ingestion adapter — selected by ``CLOUD_GRAPH_INVENTORY_SOURCE``.

        - ``finding_derived`` (default): NODES only, aggregated from the Prowler
          findings already in the SSOT (no extra AWS calls, no edges).
        - ``boto3``: the real collector — assume-role + targeted ``describe``/``list``
          for the live topology, producing NODES **and** the typed EDGES the
          attack-path analyzer walks (ADR 0005 §7 #1). Flip on per-deployment once the
          audit role can read EC2/IAM (SecurityAudit already covers it).
        The use case never changes — this is the composition-root swap (Rule 5)."""
        import os

        if os.environ.get("CLOUD_GRAPH_INVENTORY_SOURCE", "finding_derived") == "boto3":
            from components.cloud_graph.infrastructure.adapters.boto3_asset_inventory_adapter import (
                Boto3AssetInventoryAdapter,
            )

            return Boto3AssetInventoryAdapter()
        from components.cloud_graph.infrastructure.adapters.finding_derived_inventory_adapter import (
            FindingDerivedInventoryAdapter,
        )

        return FindingDerivedInventoryAdapter()

    @staticmethod
    def build_get_asset_graph_use_case():
        """The read use case the HUD's Asset Graph panel drives (nodes + edges)."""
        from components.cloud_graph.application.use_cases.get_asset_graph_use_case import (
            GetAssetGraphUseCase,
        )

        return GetAssetGraphUseCase(store=CloudGraphProvider.build_cloud_asset_store())

    @staticmethod
    def build_sync_cloud_assets_use_case():
        """The use case the ``cloud_graph.sync`` detector drives."""
        from components.cloud_graph.application.use_cases.sync_cloud_assets_use_case import (
            SyncCloudAssetsUseCase,
        )

        return SyncCloudAssetsUseCase(inventory=CloudGraphProvider.build_asset_inventory())

    @staticmethod
    def build_attack_path_store():
        """The materialised attack-path read/write store."""
        from components.cloud_graph.infrastructure.repositories.django_attack_path_repository import (
            DjangoAttackPathRepository,
        )

        return DjangoAttackPathRepository()

    @staticmethod
    def build_materialize_attack_paths_use_case():
        """The correlation JOB the ``cloud_graph.attack_paths`` detector drives — reads the
        graph, ranks toxic combinations, replaces the materialised table, emits events."""
        from components.cloud_graph.application.use_cases.materialize_attack_paths_use_case import (
            MaterializeAttackPathsUseCase,
        )
        from components.cloud_graph.domain.services.attack_path_analyzer import AttackPathAnalyzer
        from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
            CeleryEventPublisher,
        )

        return MaterializeAttackPathsUseCase(
            asset_store=CloudGraphProvider.build_cloud_asset_store(),
            path_store=CloudGraphProvider.build_attack_path_store(),
            analyzer=AttackPathAnalyzer(),
            publisher=CeleryEventPublisher(),
        )

    @staticmethod
    def build_list_attack_paths_use_case():
        """The read use case the HUD's attack-path list drives (ranked)."""
        from components.cloud_graph.application.use_cases.list_attack_paths_use_case import (
            ListAttackPathsUseCase,
        )

        return ListAttackPathsUseCase(path_store=CloudGraphProvider.build_attack_path_store())
