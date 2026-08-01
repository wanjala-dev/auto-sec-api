"""ORM ↔ domain entity mappers for the cloud asset graph."""

from __future__ import annotations

from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.domain.value_objects.enums import AssetRelation, Exposure


def to_asset_entity(obj) -> CloudAssetEntity:
    return CloudAssetEntity(
        id=obj.id,
        workspace_id=obj.workspace_id,
        aws_account_link_id=obj.aws_account_link_id,
        provider=obj.provider,
        arn=obj.arn,
        asset_urn=obj.asset_urn,
        resource_type=obj.resource_type,
        exposure=Exposure.from_value(obj.exposure),
        region=obj.region,
        name=obj.name,
        attributes=dict(obj.attributes or {}),
        first_seen_at=obj.first_seen_at,
        last_seen_at=obj.last_seen_at,
        is_deleted=obj.is_deleted,
        is_sample=obj.is_sample,
    )


def to_asset_update_defaults(asset: CloudAssetEntity) -> dict:
    """Writable fields for an UPDATE — excludes the identity (workspace, arn) and
    ``first_seen_at`` so a re-sync never rewrites when the asset was first observed."""
    return {
        "aws_account_link_id": asset.aws_account_link_id,
        "provider": asset.provider,
        "asset_urn": asset.asset_urn,
        "resource_type": asset.resource_type,
        "region": asset.region,
        "name": asset.name,
        "exposure": asset.exposure.value,
        "attributes": asset.attributes,
        "last_seen_at": asset.last_seen_at,
        "is_deleted": asset.is_deleted,
        "is_sample": asset.is_sample,
    }


def to_edge_entity(obj) -> CloudAssetEdgeEntity:
    return CloudAssetEdgeEntity(
        id=obj.id,
        workspace_id=obj.workspace_id,
        src_asset_id=obj.src_asset_id,
        dst_asset_id=obj.dst_asset_id,
        relation=AssetRelation.from_value(obj.relation),
        attributes=dict(obj.attributes or {}),
        last_seen_at=obj.last_seen_at,
        is_sample=obj.is_sample,
    )


def to_edge_defaults(edge: CloudAssetEdgeEntity) -> dict:
    return {
        "workspace_id": edge.workspace_id,
        "attributes": edge.attributes,
        "last_seen_at": edge.last_seen_at,
        "is_sample": edge.is_sample,
    }
