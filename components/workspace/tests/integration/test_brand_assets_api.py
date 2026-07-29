"""Integration: brand asset library — API scoping + recycle-bin lifecycle."""

from __future__ import annotations

import uuid as _uuid

import pytest

from components.recycle_bin.application.commands.restore_command import RestoreCommand
from components.recycle_bin.application.commands.trash_command import TrashCommand
from components.recycle_bin.application.providers.recycle_bin_provider import (
    get_recycle_bin_service,
)
from components.workspace.application.providers.brand_asset_provider import (
    get_brand_asset_provider,
)

pytestmark = [pytest.mark.django_db]


def _create_asset(workspace_id, **overrides):
    payload = {"url": "https://cdn.example/photo.jpg", "label": "Hero shot"}
    payload.update(overrides)
    return get_brand_asset_provider().build_create_use_case().execute(workspace_id, **payload)


class TestBrandAssetUseCasesDb:
    def test_create_list_round_trip(self, workspace_factory):
        workspace = workspace_factory()
        created = _create_asset(workspace.id)

        listed = get_brand_asset_provider().build_list_use_case().execute(workspace.id)
        assert [a["id"] for a in listed] == [created["id"]]
        assert listed[0]["label"] == "Hero shot"

    def test_listing_is_workspace_scoped(self, workspace_factory):
        ws_a, ws_b = workspace_factory(), workspace_factory()
        _create_asset(ws_a.id)

        assert get_brand_asset_provider().build_list_use_case().execute(ws_b.id) == []

    def test_caption_update(self, workspace_factory):
        workspace = workspace_factory()
        created = _create_asset(workspace.id)
        updated = (
            get_brand_asset_provider()
            .build_update_use_case()
            .execute(workspace.id, created["id"], label="Renamed", alt_text="Kids reading")
        )
        assert updated["label"] == "Renamed"
        assert updated["alt_text"] == "Kids reading"


class TestBrandAssetRecycleBinLifecycle:
    def test_trash_restore_purge(self, workspace_factory, user_factory):
        from infrastructure.persistence.workspaces.theming.models import BrandAsset

        actor = user_factory()
        workspace = workspace_factory()
        created = _create_asset(workspace.id, storage_key="media/brand/photo.jpg")
        service = get_recycle_bin_service()

        # Trash — asset disappears from the library list but the row survives.
        entry = service.trash(
            TrashCommand(
                workspace_id=workspace.id,
                entity_type="brand_asset",
                entity_id=str(created["id"]),
                deleted_by=actor.id,
            )
        )
        assert get_brand_asset_provider().build_list_use_case().execute(workspace.id) == []
        assert BrandAsset.objects.filter(id=created["id"], deleted=True).exists()

        # Restore — it reappears.
        service.restore(RestoreCommand(entry_id=entry.id, restored_by=actor.id))
        listed = get_brand_asset_provider().build_list_use_case().execute(workspace.id)
        assert [a["id"] for a in listed] == [created["id"]]

        # Trash again, then purge — the row is gone for good.
        entry2 = service.trash(
            TrashCommand(
                workspace_id=workspace.id,
                entity_type="brand_asset",
                entity_id=str(created["id"]),
                deleted_by=actor.id,
            )
        )
        service.permanently_delete_one(entry_id=entry2.id, deleted_by=actor.id)
        assert not BrandAsset.objects.filter(id=created["id"]).exists()


class TestBrandAssetEndpoints:
    def test_endpoints_require_workspace_admin(self, api_client, workspace_factory):
        workspace = workspace_factory()
        response = api_client.get(f"/workspaces/{workspace.id}/brand/assets/")
        assert response.status_code in (401, 403)

    def test_admin_create_and_list(self, api_client, workspace_factory):
        workspace = workspace_factory()
        api_client.force_authenticate(workspace.workspace_owner)

        create = api_client.post(
            f"/workspaces/{workspace.id}/brand/assets/",
            {"url": "https://cdn.example/team.jpg", "label": "Team", "kind": "photo"},
            format="json",
        )
        assert create.status_code == 201, create.content

        listed = api_client.get(f"/workspaces/{workspace.id}/brand/assets/")
        assert listed.status_code == 200
        assert len(listed.data["data"]) == 1
        assert listed.data["data"][0]["url"] == "https://cdn.example/team.jpg"

    def test_create_rejects_missing_url(self, api_client, workspace_factory):
        workspace = workspace_factory()
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.post(f"/workspaces/{workspace.id}/brand/assets/", {"label": "No url"}, format="json")
        assert response.status_code == 400

    def test_caption_patch(self, api_client, workspace_factory):
        workspace = workspace_factory()
        api_client.force_authenticate(workspace.workspace_owner)
        created = _create_asset(workspace.id)

        response = api_client.patch(
            f"/workspaces/{workspace.id}/brand/assets/{created['id']}/",
            {"label": "Renamed"},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert response.data["data"]["label"] == "Renamed"

    def test_patch_unknown_asset_404(self, api_client, workspace_factory):
        workspace = workspace_factory()
        api_client.force_authenticate(workspace.workspace_owner)
        response = api_client.patch(
            f"/workspaces/{workspace.id}/brand/assets/{_uuid.uuid4()}/",
            {"label": "x"},
            format="json",
        )
        assert response.status_code == 404
