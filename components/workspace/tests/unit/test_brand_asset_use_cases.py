"""Unit tests for the brand asset use cases (fake store — no DB)."""

from __future__ import annotations

import uuid
from uuid import UUID, uuid4

import pytest

from components.workspace.application.ports.brand_asset_store_port import BrandAssetStorePort
from components.workspace.application.use_cases.create_brand_asset_use_case import (
    CreateBrandAssetUseCase,
)
from components.workspace.application.use_cases.list_brand_assets_use_case import (
    ListBrandAssetsUseCase,
)
from components.workspace.application.use_cases.update_brand_asset_use_case import (
    UpdateBrandAssetUseCase,
)
from components.workspace.domain.entities.brand_asset_entity import BrandAssetEntity
from components.workspace.domain.errors import WorkspaceNotFoundError, WorkspaceValidationError


class FakeStore(BrandAssetStorePort):
    def __init__(self):
        self.assets: list[BrandAssetEntity] = []

    def list_for_workspace(self, workspace_id: UUID) -> list[BrandAssetEntity]:
        return [a for a in self.assets if a.workspace_id == str(workspace_id) and not a.deleted]

    def create(self, workspace_id: UUID, **kwargs) -> BrandAssetEntity:
        asset = BrandAssetEntity(
            id=str(uuid.uuid4()),
            workspace_id=str(workspace_id),
            url=kwargs["url"],
            storage_key=kwargs.get("storage_key", ""),
            label=kwargs.get("label", ""),
            alt_text=kwargs.get("alt_text", ""),
            kind=kwargs.get("kind", "photo"),
        )
        self.assets.append(asset)
        return asset

    def update_meta(self, workspace_id, asset_id, *, label=None, alt_text=None):
        for i, a in enumerate(self.assets):
            if a.id == str(asset_id) and a.workspace_id == str(workspace_id):
                updated = BrandAssetEntity(
                    id=a.id,
                    workspace_id=a.workspace_id,
                    url=a.url,
                    label=label if label is not None else a.label,
                    alt_text=alt_text if alt_text is not None else a.alt_text,
                    kind=a.kind,
                )
                self.assets[i] = updated
                return updated
        return None


class TestCreateBrandAsset:
    def test_creates_and_returns_dict(self):
        store = FakeStore()
        ws = uuid4()
        result = CreateBrandAssetUseCase(store).execute(ws, url="https://cdn.example/team.jpg", label="Team photo")
        assert result["url"] == "https://cdn.example/team.jpg"
        assert result["label"] == "Team photo"
        assert result["kind"] == "photo"
        assert len(store.assets) == 1

    def test_rejects_blank_url(self):
        with pytest.raises(WorkspaceValidationError):
            CreateBrandAssetUseCase(FakeStore()).execute(uuid4(), url="   ")

    def test_rejects_unknown_kind(self):
        with pytest.raises(WorkspaceValidationError):
            CreateBrandAssetUseCase(FakeStore()).execute(uuid4(), url="https://cdn.example/x.jpg", kind="video")


class TestListBrandAssets:
    def test_lists_only_this_workspace(self):
        store = FakeStore()
        ws_a, ws_b = uuid4(), uuid4()
        create = CreateBrandAssetUseCase(store)
        create.execute(ws_a, url="https://cdn.example/a.jpg")
        create.execute(ws_b, url="https://cdn.example/b.jpg")

        listed = ListBrandAssetsUseCase(store).execute(ws_a)
        assert len(listed) == 1
        assert listed[0]["url"] == "https://cdn.example/a.jpg"


class TestUpdateBrandAsset:
    def test_updates_caption(self):
        store = FakeStore()
        ws = uuid4()
        created = CreateBrandAssetUseCase(store).execute(ws, url="https://cdn.example/a.jpg")
        updated = UpdateBrandAssetUseCase(store).execute(ws, created["id"], label="New label")
        assert updated["label"] == "New label"

    def test_missing_asset_raises_not_found(self):
        with pytest.raises(WorkspaceNotFoundError):
            UpdateBrandAssetUseCase(FakeStore()).execute(uuid4(), uuid4(), label="x")
