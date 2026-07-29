"""Repository: BrandAsset persistence (implements BrandAssetStorePort)."""

from __future__ import annotations

from uuid import UUID

from components.workspace.application.ports.brand_asset_store_port import BrandAssetStorePort
from components.workspace.domain.entities.brand_asset_entity import BrandAssetEntity
from components.workspace.mappers.db.brand_asset_mapper import to_brand_asset_entity


class BrandAssetRepository(BrandAssetStorePort):
    def list_for_workspace(self, workspace_id: UUID) -> list[BrandAssetEntity]:
        from infrastructure.persistence.workspaces.theming.models import BrandAsset

        rows = BrandAsset.objects.filter(workspace_id=workspace_id, deleted=False)
        return [to_brand_asset_entity(row) for row in rows]

    def create(
        self,
        workspace_id: UUID,
        *,
        url: str,
        storage_key: str = "",
        label: str = "",
        alt_text: str = "",
        kind: str = "photo",
        uploaded_by_id: int | None = None,
    ) -> BrandAssetEntity:
        from infrastructure.persistence.workspaces.theming.models import BrandAsset

        row = BrandAsset.objects.create(
            workspace_id=workspace_id,
            url=url,
            storage_key=storage_key,
            label=label,
            alt_text=alt_text,
            kind=kind,
            uploaded_by_id=uploaded_by_id,
        )
        return to_brand_asset_entity(row)

    def update_meta(
        self,
        workspace_id: UUID,
        asset_id: UUID,
        *,
        label: str | None = None,
        alt_text: str | None = None,
    ) -> BrandAssetEntity | None:
        from infrastructure.persistence.workspaces.theming.models import BrandAsset

        row = BrandAsset.objects.filter(id=asset_id, workspace_id=workspace_id, deleted=False).first()
        if row is None:
            return None
        update_fields = ["updated_at"]
        if label is not None:
            row.label = label
            update_fields.append("label")
        if alt_text is not None:
            row.alt_text = alt_text
            update_fields.append("alt_text")
        row.save(update_fields=update_fields)
        return to_brand_asset_entity(row)
