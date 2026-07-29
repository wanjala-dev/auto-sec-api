"""Port: persistence of a workspace's brand asset library (outbound / driven).

No delete method by design — deletion routes through the recycle bin's
``SoftDeletePort`` adapter (``entity_type="brand_asset"``), never a direct
endpoint.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from components.workspace.domain.entities.brand_asset_entity import BrandAssetEntity


class BrandAssetStorePort(ABC):
    @abstractmethod
    def list_for_workspace(self, workspace_id: UUID) -> list[BrandAssetEntity]:
        """Non-deleted assets, newest first."""

    @abstractmethod
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
    ) -> BrandAssetEntity: ...

    @abstractmethod
    def update_meta(
        self,
        workspace_id: UUID,
        asset_id: UUID,
        *,
        label: str | None = None,
        alt_text: str | None = None,
    ) -> BrandAssetEntity | None:
        """Update caption metadata; returns ``None`` when not found."""
