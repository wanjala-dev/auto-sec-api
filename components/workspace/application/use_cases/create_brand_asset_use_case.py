"""Use case: register an uploaded image in the workspace's brand library.

The bytes are already in object storage (shared presigned-PUT flow) — this
records the URL + metadata as a library row. Validates the URL is present and
the kind is in the contract.
"""

from __future__ import annotations

from uuid import UUID

from components.workspace.application.ports.brand_asset_store_port import BrandAssetStorePort
from components.workspace.domain.entities.brand_asset_entity import BRAND_ASSET_KINDS
from components.workspace.domain.errors import WorkspaceValidationError


class CreateBrandAssetUseCase:
    def __init__(self, store: BrandAssetStorePort) -> None:
        self._store = store

    def execute(
        self,
        workspace_id: UUID,
        *,
        url: str,
        storage_key: str = "",
        label: str = "",
        alt_text: str = "",
        kind: str = "photo",
        uploaded_by_id: int | None = None,
    ) -> dict:
        if not (url or "").strip():
            raise WorkspaceValidationError("A brand asset needs an uploaded file URL.")
        kind = (kind or "photo").strip() or "photo"
        if kind not in BRAND_ASSET_KINDS:
            raise WorkspaceValidationError(f"Unknown brand asset kind {kind!r}; expected one of {BRAND_ASSET_KINDS}.")
        asset = self._store.create(
            workspace_id,
            url=url.strip(),
            storage_key=(storage_key or "").strip(),
            label=(label or "").strip(),
            alt_text=(alt_text or "").strip(),
            kind=kind,
            uploaded_by_id=uploaded_by_id,
        )
        return asset.as_dict()
