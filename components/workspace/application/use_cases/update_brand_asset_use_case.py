"""Use case: update a brand asset's caption metadata (label / alt text)."""

from __future__ import annotations

from uuid import UUID

from components.workspace.application.ports.brand_asset_store_port import BrandAssetStorePort
from components.workspace.domain.errors import WorkspaceNotFoundError


class UpdateBrandAssetUseCase:
    def __init__(self, store: BrandAssetStorePort) -> None:
        self._store = store

    def execute(
        self,
        workspace_id: UUID,
        asset_id: UUID,
        *,
        label: str | None = None,
        alt_text: str | None = None,
    ) -> dict:
        asset = self._store.update_meta(
            workspace_id,
            asset_id,
            label=label.strip() if isinstance(label, str) else None,
            alt_text=alt_text.strip() if isinstance(alt_text, str) else None,
        )
        if asset is None:
            raise WorkspaceNotFoundError("Brand asset not found.")
        return asset.as_dict()
