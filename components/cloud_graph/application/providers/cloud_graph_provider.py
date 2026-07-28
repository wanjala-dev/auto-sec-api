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
        """The ingestion adapter (spike §5). A composite: the finding/SSOT-derived source
        for node breadth + the boto3 source for relationship depth (typed edges → attack
        paths). boto3 is a no-op for workspaces without AWS account access, so the composite
        is always safe to run."""
        from components.cloud_graph.infrastructure.adapters.boto3_inventory_adapter import (
            Boto3InventoryAdapter,
        )
        from components.cloud_graph.infrastructure.adapters.composite_inventory_adapter import (
            CompositeInventoryAdapter,
        )
        from components.cloud_graph.infrastructure.adapters.finding_derived_inventory_adapter import (
            FindingDerivedInventoryAdapter,
        )

        return CompositeInventoryAdapter([FindingDerivedInventoryAdapter(), Boto3InventoryAdapter()])

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
    def build_get_risk_score_use_case():
        """The read use case backing the workspace risk-score gauge (attack-path-led rollup).

        Reads the findings SSOT (via the findings context's public store port, C3) for
        severity counts + the materialised attack paths — cross-context reads through ports,
        never another context's ORM."""
        from components.cloud_graph.application.use_cases.get_risk_score_use_case import (
            GetRiskScoreUseCase,
        )
        from components.findings.application.providers.finding_provider import FindingProvider

        return GetRiskScoreUseCase(
            finding_store=FindingProvider.build_finding_store(),
            attack_path_store=CloudGraphProvider.build_attack_path_store(),
        )

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
