"""Use case: list a workspace's brand asset library (non-deleted, newest first)."""

from __future__ import annotations

from uuid import UUID

from components.workspace.application.ports.brand_asset_store_port import BrandAssetStorePort


class ListBrandAssetsUseCase:
    def __init__(self, store: BrandAssetStorePort) -> None:
        self._store = store

    def execute(self, workspace_id: UUID) -> list[dict]:
        return [asset.as_dict() for asset in self._store.list_for_workspace(workspace_id)]
