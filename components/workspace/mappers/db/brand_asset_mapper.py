"""Mapper: ORM ``BrandAsset`` -> ``BrandAssetEntity``."""

from __future__ import annotations

from components.workspace.domain.entities.brand_asset_entity import BrandAssetEntity


def to_brand_asset_entity(model) -> BrandAssetEntity:
    return BrandAssetEntity(
        id=str(model.id),
        workspace_id=str(model.workspace_id),
        url=model.url or "",
        storage_key=model.storage_key or "",
        label=model.label or "",
        alt_text=model.alt_text or "",
        kind=model.kind or "photo",
        deleted=bool(model.deleted),
        created_at=model.created_at.isoformat() if model.created_at else "",
    )
