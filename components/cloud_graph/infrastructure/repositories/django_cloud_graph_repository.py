"""Django adapter implementing CloudAssetStorePort — idempotent graph upserts."""

from __future__ import annotations

from uuid import UUID

from components.cloud_graph.application.ports.cloud_asset_store_port import CloudAssetStorePort
from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.mappers.db.cloud_asset_mapper import (
    to_asset_entity,
    to_asset_update_defaults,
    to_edge_defaults,
    to_edge_entity,
)


class DjangoCloudGraphRepository(CloudAssetStorePort):
    def upsert_asset(self, asset: CloudAssetEntity) -> CloudAssetEntity:
        from infrastructure.persistence.cloud_graph.models import CloudAsset

        # Identity = (workspace, arn). On UPDATE we preserve first_seen_at; on CREATE we
        # set it. update_or_create can't do conditional defaults, so branch explicitly.
        obj = CloudAsset.objects.filter(workspace_id=asset.workspace_id, arn=asset.arn).first()
        if obj is None:
            obj = CloudAsset.objects.create(
                id=asset.id,
                workspace_id=asset.workspace_id,
                arn=asset.arn,
                first_seen_at=asset.first_seen_at,
                **to_asset_update_defaults(asset),
            )
        else:
            for key, value in to_asset_update_defaults(asset).items():
                setattr(obj, key, value)
            obj.save()
        return to_asset_entity(obj)

    def upsert_edge(self, edge: CloudAssetEdgeEntity) -> CloudAssetEdgeEntity:
        from infrastructure.persistence.cloud_graph.models import CloudAssetEdge

        obj, _ = CloudAssetEdge.objects.update_or_create(
            src_asset_id=edge.src_asset_id,
            dst_asset_id=edge.dst_asset_id,
            relation=edge.relation.value,
            defaults=to_edge_defaults(edge),
        )
        return to_edge_entity(obj)

    def get_asset_by_arn(self, workspace_id: UUID, arn: str) -> CloudAssetEntity | None:
        from infrastructure.persistence.cloud_graph.models import CloudAsset

        obj = CloudAsset.objects.filter(workspace_id=workspace_id, arn=arn).select_related("workspace").first()
        return to_asset_entity(obj) if obj else None

    def list_assets(
        self,
        workspace_id: UUID,
        *,
        resource_type: str | None = None,
        exposure: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[CloudAssetEntity]:
        from infrastructure.persistence.cloud_graph.models import CloudAsset

        qs = CloudAsset.objects.filter(workspace_id=workspace_id, is_deleted=False)
        if resource_type:
            qs = qs.filter(resource_type=resource_type)
        if exposure:
            qs = qs.filter(exposure=exposure)
        rows = qs.select_related("workspace").order_by("-last_seen_at")[offset : offset + limit]
        return [to_asset_entity(obj) for obj in rows]

    def count_by_exposure(self, workspace_id: UUID) -> dict[str, int]:
        from django.db.models import Count

        from infrastructure.persistence.cloud_graph.models import CloudAsset

        rows = (
            CloudAsset.objects.filter(workspace_id=workspace_id, is_deleted=False)
            .values("exposure")
            .annotate(n=Count("id"))
        )
        return {r["exposure"]: r["n"] for r in rows}

    def count_by_type(self, workspace_id: UUID, *, top: int = 8) -> list[tuple[str, int]]:
        from django.db.models import Count

        from infrastructure.persistence.cloud_graph.models import CloudAsset

        rows = (
            CloudAsset.objects.filter(workspace_id=workspace_id, is_deleted=False)
            .values("resource_type")
            .annotate(n=Count("id"))
            .order_by("-n")[:top]
        )
        return [(r["resource_type"], r["n"]) for r in rows]

    def list_public_asset_urns(self, workspace_id: UUID) -> list[str]:
        from infrastructure.persistence.cloud_graph.models import CloudAsset

        return list(
            CloudAsset.objects.filter(workspace_id=workspace_id, is_deleted=False, exposure="public")
            .exclude(asset_urn="")
            .values_list("asset_urn", flat=True)
        )

    def list_edges_from(self, workspace_id: UUID, src_asset_id: UUID) -> list[CloudAssetEdgeEntity]:
        from infrastructure.persistence.cloud_graph.models import CloudAssetEdge

        rows = CloudAssetEdge.objects.filter(workspace_id=workspace_id, src_asset_id=src_asset_id)
        return [to_edge_entity(obj) for obj in rows]

    def list_all_edges(self, workspace_id: UUID, *, limit: int = 2000) -> list[CloudAssetEdgeEntity]:
        from infrastructure.persistence.cloud_graph.models import CloudAssetEdge

        rows = CloudAssetEdge.objects.filter(workspace_id=workspace_id).order_by("-last_seen_at")[:limit]
        return [to_edge_entity(obj) for obj in rows]

    # ── Sample/demo data (ADR 0011) ───────────────────────────────────────────

    def has_real_assets(self, workspace_id: UUID) -> bool:
        from infrastructure.persistence.cloud_graph.models import CloudAsset

        return CloudAsset.objects.filter(workspace_id=workspace_id, is_sample=False).exists()

    def seed_sample_graph(
        self,
        workspace_id: UUID,
        assets: list[CloudAssetEntity],
        edges: list[CloudAssetEdgeEntity],
    ) -> tuple[int, int]:
        from django.db import transaction

        from infrastructure.persistence.cloud_graph.models import CloudAsset, CloudAssetEdge

        with transaction.atomic():
            # Clear sample-first so re-seeding never collides on uniq_cloud_asset_identity
            # (deleting the sample assets cascades their sample edges). Real rows untouched.
            CloudAsset.objects.filter(workspace_id=workspace_id, is_sample=True).delete()
            CloudAsset.objects.bulk_create(
                CloudAsset(
                    id=a.id,
                    workspace_id=a.workspace_id,
                    arn=a.arn,
                    first_seen_at=a.first_seen_at,
                    **to_asset_update_defaults(a),
                )
                for a in assets
            )
            CloudAssetEdge.objects.bulk_create(
                CloudAssetEdge(
                    id=e.id,
                    src_asset_id=e.src_asset_id,
                    dst_asset_id=e.dst_asset_id,
                    relation=e.relation.value,
                    **to_edge_defaults(e),
                )
                for e in edges
            )
        return len(assets), len(edges)

    def clear_sample_assets(self, workspace_id: UUID) -> int:
        from infrastructure.persistence.cloud_graph.models import CloudAsset

        # Edges FK-cascade off their assets, so deleting the sample assets removes the
        # sample edges too; any sample edge whose endpoints were both sample assets is
        # thus cleared without a second pass.
        deleted, _ = CloudAsset.objects.filter(workspace_id=workspace_id, is_sample=True).delete()
        return deleted
