"""Composition root for the brand asset library use cases + the soft-delete
adapter consumed by the recycle-bin context."""

from __future__ import annotations

from typing import Any

from components.workspace.application.use_cases.create_brand_asset_use_case import (
    CreateBrandAssetUseCase,
)
from components.workspace.application.use_cases.list_brand_assets_use_case import (
    ListBrandAssetsUseCase,
)
from components.workspace.application.use_cases.update_brand_asset_use_case import (
    UpdateBrandAssetUseCase,
)
from components.workspace.infrastructure.repositories.brand_asset_repository import (
    BrandAssetRepository,
)


class BrandAssetProvider:
    @staticmethod
    def build_list_use_case() -> ListBrandAssetsUseCase:
        return ListBrandAssetsUseCase(BrandAssetRepository())

    @staticmethod
    def build_create_use_case() -> CreateBrandAssetUseCase:
        return CreateBrandAssetUseCase(BrandAssetRepository())

    @staticmethod
    def build_update_use_case() -> UpdateBrandAssetUseCase:
        return UpdateBrandAssetUseCase(BrandAssetRepository())

    @staticmethod
    def soft_delete_adapter() -> Any:
        from components.workspace.infrastructure.adapters.brand_asset_soft_delete_adapter import (
            BrandAssetSoftDeleteAdapter,
        )

        return BrandAssetSoftDeleteAdapter()


def get_brand_asset_provider() -> BrandAssetProvider:
    return BrandAssetProvider()
