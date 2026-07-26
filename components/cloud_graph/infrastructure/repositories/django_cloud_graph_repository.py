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

    def list_edges_from(self, workspace_id: UUID, src_asset_id: UUID) -> list[CloudAssetEdgeEntity]:
        from infrastructure.persistence.cloud_graph.models import CloudAssetEdge

        rows = CloudAssetEdge.objects.filter(workspace_id=workspace_id, src_asset_id=src_asset_id)
        return [to_edge_entity(obj) for obj in rows]

    def list_all_edges(self, workspace_id: UUID, *, limit: int = 2000) -> list[CloudAssetEdgeEntity]:
        from infrastructure.persistence.cloud_graph.models import CloudAssetEdge

        rows = CloudAssetEdge.objects.filter(workspace_id=workspace_id).order_by("-last_seen_at")[:limit]
        return [to_edge_entity(obj) for obj in rows]
