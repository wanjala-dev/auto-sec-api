"""Tag vocabulary CRUD API (ADR 0015 D6) — gates, uniqueness, soft-delete/restore,
system-kind protection, workspace scoping."""

from __future__ import annotations

import pytest

from infrastructure.persistence.tagging.models import Tag
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.django_db]


def _url(ws):
    return f"/api/v1/tagging/workspaces/{ws.id}/tags/"


def _detail_url(ws, tag_id):
    return f"/api/v1/tagging/workspaces/{ws.id}/tags/{tag_id}/"


def _member(ws, user_factory, *, role="member"):
    user = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=user, role=role, status="active")
    return user


class TestTagCreate:
    def test_member_creates_tag(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        api_client.force_authenticate(_member(ws, user_factory))
        resp = api_client.post(_url(ws), {"name": "Env: Prod"}, format="json")
        assert resp.status_code == 201, resp.data
        data = resp.data["data"]
        assert data["slug"] == "env:prod"
        assert data["namespace"] == "env"
        assert data["name"] == "Prod"
        assert data["kind"] == "user"

    def test_namespace_field_variant(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        api_client.force_authenticate(_member(ws, user_factory))
        resp = api_client.post(_url(ws), {"name": "Payments", "namespace": "owner", "color": "#2EDBE8"}, format="json")
        assert resp.status_code == 201, resp.data
        assert resp.data["data"]["slug"] == "owner:payments"
        assert resp.data["data"]["color"] == "#2EDBE8"

    def test_duplicate_is_409_case_insensitively(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        api_client.force_authenticate(_member(ws, user_factory))
        assert api_client.post(_url(ws), {"name": "macOS"}, format="json").status_code == 201
        resp = api_client.post(_url(ws), {"name": "MACOS"}, format="json")
        assert resp.status_code == 409
        assert resp.data["error"] == "duplicate_tag"

    def test_invalid_name_is_400(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        api_client.force_authenticate(_member(ws, user_factory))
        resp = api_client.post(_url(ws), {"name": "a::b"}, format="json")
        assert resp.status_code == 400
        assert resp.data["error"] == "invalid_tag"

    def test_invalid_color_is_400(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        api_client.force_authenticate(_member(ws, user_factory))
        resp = api_client.post(_url(ws), {"name": "ok", "color": "red"}, format="json")
        assert resp.status_code == 400

    def test_risk_namespace_is_reserved(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        api_client.force_authenticate(_member(ws, user_factory))
        resp = api_client.post(_url(ws), {"name": "risk:accepted"}, format="json")
        assert resp.status_code == 400
        assert resp.data["error"] == "reserved_tag"

    def test_non_member_forbidden(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        api_client.force_authenticate(user_factory())
        assert api_client.post(_url(ws), {"name": "x"}, format="json").status_code == 403

    def test_requires_authentication(self, api_client, workspace_factory):
        ws = workspace_factory()
        assert api_client.post(_url(ws), {"name": "x"}, format="json").status_code in (401, 403)


class TestTagList:
    def test_list_is_workspace_scoped_and_live_only(self, api_client, workspace_factory, user_factory):
        ws_a, ws_b = workspace_factory(), workspace_factory()
        member = _member(ws_a, user_factory)
        api_client.force_authenticate(member)
        api_client.post(_url(ws_a), {"name": "env:prod"}, format="json")
        Tag.objects.create(workspace=ws_b, name="other", slug="other")
        Tag.objects.create(workspace=ws_a, name="dead", slug="dead", is_deleted=True)

        resp = api_client.get(_url(ws_a))
        assert resp.status_code == 200
        slugs = [t["slug"] for t in resp.data["data"]["items"]]
        assert slugs == ["env:prod"]
        assert resp.data["data"]["total"] == 1

    def test_namespace_and_q_filters(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        api_client.force_authenticate(_member(ws, user_factory))
        for name in ("env:prod", "env:staging", "team:payments"):
            api_client.post(_url(ws), {"name": name}, format="json")

        by_ns = api_client.get(_url(ws), {"namespace": "env"}).data["data"]
        assert {t["slug"] for t in by_ns["items"]} == {"env:prod", "env:staging"}
        by_q = api_client.get(_url(ws), {"q": "pay"}).data["data"]
        assert [t["slug"] for t in by_q["items"]] == ["team:payments"]

    def test_include_usage_annotates(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        api_client.force_authenticate(_member(ws, user_factory))
        api_client.post(_url(ws), {"name": "unused"}, format="json")
        resp = api_client.get(_url(ws), {"include_usage": "1"})
        assert resp.data["data"]["items"][0]["usage_count"] == 0


class TestTagUpdateAndDelete:
    def _seed(self, api_client, ws, user_factory, name="env:prod"):
        api_client.force_authenticate(_member(ws, user_factory))
        resp = api_client.post(_url(ws), {"name": name}, format="json")
        return resp.data["data"]["id"]

    def test_member_cannot_rename_or_delete(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        tag_id = self._seed(api_client, ws, user_factory)
        api_client.force_authenticate(_member(ws, user_factory))  # plain member
        assert api_client.patch(_detail_url(ws, tag_id), {"name": "flat-new"}, format="json").status_code == 403
        assert api_client.delete(_detail_url(ws, tag_id)).status_code == 403

    def test_admin_rename_reslugs(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        tag_id = self._seed(api_client, ws, user_factory, name="Needs Review")
        api_client.force_authenticate(_member(ws, user_factory, role="admin"))
        resp = api_client.patch(_detail_url(ws, tag_id), {"name": "Triaged Today"}, format="json")
        assert resp.status_code == 200, resp.data
        assert resp.data["data"]["slug"] == "triaged-today"
        assert resp.data["data"]["name"] == "Triaged Today"
        assert resp.data["data"]["id"] == tag_id  # the UUID is the stable identity (D5)

    def test_rename_into_live_slug_is_409(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        self._seed(api_client, ws, user_factory, name="alpha")
        tag_id = self._seed(api_client, ws, user_factory, name="beta")
        api_client.force_authenticate(_member(ws, user_factory, role="admin"))
        assert api_client.patch(_detail_url(ws, tag_id), {"name": "Alpha"}, format="json").status_code == 409

    def test_rename_cannot_cross_reserved_namespace_boundary(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        tag_id = self._seed(api_client, ws, user_factory, name="plain")
        api_client.force_authenticate(_member(ws, user_factory, role="admin"))
        resp = api_client.patch(_detail_url(ws, tag_id), {"name": "env:plain"}, format="json")
        assert resp.status_code == 400
        assert resp.data["error"] == "reserved_tag"

    def test_owner_soft_delete_then_recreate_then_restore_conflicts(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        tag_id = self._seed(api_client, ws, user_factory, name="ephemeral")
        admin = _member(ws, user_factory, role="owner")
        api_client.force_authenticate(admin)

        # Soft delete — the row is retained, just not live.
        assert api_client.delete(_detail_url(ws, tag_id)).status_code == 200
        row = Tag.objects.get(id=tag_id)
        assert row.is_deleted is True
        assert [t["slug"] for t in api_client.get(_url(ws)).data["data"]["items"]] == []

        # A live namesake may coexist with the dead row (conditional uniqueness).
        resp = api_client.post(_url(ws), {"name": "ephemeral"}, format="json")
        assert resp.status_code == 201

        # Restoring the dead row now clashes with the live namesake → 409.
        resp = api_client.patch(_detail_url(ws, tag_id), {"is_deleted": False}, format="json")
        assert resp.status_code == 409

    def test_restore_without_clash_succeeds(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        tag_id = self._seed(api_client, ws, user_factory, name="phoenix")
        api_client.force_authenticate(_member(ws, user_factory, role="admin"))
        api_client.delete(_detail_url(ws, tag_id))
        resp = api_client.patch(_detail_url(ws, tag_id), {"is_deleted": False}, format="json")
        assert resp.status_code == 200
        assert resp.data["data"]["is_deleted"] is False

    def test_system_tag_is_write_protected(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        system_tag = Tag.objects.create(workspace=ws, name="platform", slug="platform", kind="system")
        api_client.force_authenticate(_member(ws, user_factory, role="owner"))
        patch = api_client.patch(_detail_url(ws, system_tag.id), {"name": "hijack"}, format="json")
        assert patch.status_code == 400
        assert patch.data["error"] == "reserved_tag"
        delete = api_client.delete(_detail_url(ws, system_tag.id))
        assert delete.status_code == 400
        assert Tag.objects.get(id=system_tag.id).is_deleted is False

    def test_cross_workspace_tag_is_404(self, api_client, workspace_factory, user_factory):
        ws_a, ws_b = workspace_factory(), workspace_factory()
        tag_id = self._seed(api_client, ws_a, user_factory)
        api_client.force_authenticate(_member(ws_b, user_factory, role="admin"))
        assert api_client.patch(_detail_url(ws_b, tag_id), {"name": "steal"}, format="json").status_code == 404
