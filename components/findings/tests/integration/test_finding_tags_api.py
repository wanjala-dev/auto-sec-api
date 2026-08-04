"""Tag/untag a finding — POST /findings/workspaces/<ws>/<finding_id>/tags/ (ADR 0015 D6)
plus the tag filter algebra on the findings list (D7)."""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from infrastructure.persistence.findings.models import Finding, FindingTag
from infrastructure.persistence.tagging.models import Tag
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.django_db]


def _tags_url(ws, finding):
    return f"/api/v1/findings/workspaces/{ws.id}/{finding.id}/tags/"


def _list_url(ws):
    return f"/api/v1/findings/workspaces/{ws.id}/"


def _member(ws, user_factory):
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    return member


def _finding(ws, *, fingerprint=None):
    now = timezone.now()
    return Finding.objects.create(
        workspace=ws,
        source="cloud_posture.prowler",
        fingerprint=fingerprint or f"fp-{uuid.uuid4()}",
        asset_urn=f"arn:aws:s3:::{uuid.uuid4()}",
        severity="high",
        status="open",
        title="Public bucket",
        first_seen_at=now,
        last_seen_at=now,
    )


class TestFindingTagEndpoint:
    def test_add_auto_creates_and_returns_full_tag_set(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)
        api_client.force_authenticate(member)

        resp = api_client.post(_tags_url(ws, finding), {"add": ["Env: Prod", "needs-review"]}, format="json")
        assert resp.status_code == 200, resp.data
        tags = resp.data["data"]["tags"]
        assert [t["slug"] for t in tags] == ["env:prod", "needs-review"]
        # Auto-created in the canonical vocabulary (D4), workspace-scoped.
        assert Tag.active.filter(workspace=ws, slug="env:prod", kind="user").exists()
        # Provenance stamp on the edge (D8).
        link = FindingTag.objects.get(finding=finding, tag__slug="env:prod")
        assert link.source == "user"
        assert str(link.applied_by) == str(member.id)
        assert link.workspace_id == ws.id

    def test_idempotent_re_add(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)
        api_client.force_authenticate(member)
        api_client.post(_tags_url(ws, finding), {"add": ["env:prod"]}, format="json")
        resp = api_client.post(_tags_url(ws, finding), {"add": ["env:prod"]}, format="json")
        assert resp.status_code == 200
        assert FindingTag.objects.filter(finding=finding).count() == 1
        assert Tag.active.filter(workspace=ws, slug="env:prod").count() == 1

    def test_remove_and_unknown_remove_noop(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)
        api_client.force_authenticate(member)
        api_client.post(_tags_url(ws, finding), {"add": ["env:prod", "team:payments"]}, format="json")
        resp = api_client.post(_tags_url(ws, finding), {"remove": ["team:payments", "never-existed"]}, format="json")
        assert resp.status_code == 200
        assert [t["slug"] for t in resp.data["data"]["tags"]] == ["env:prod"]
        # Removal deletes the edge but NEVER the vocabulary entry.
        assert Tag.active.filter(workspace=ws, slug="team:payments").exists()

    def test_empty_body_is_400(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)
        api_client.force_authenticate(member)
        assert api_client.post(_tags_url(ws, finding), {}, format="json").status_code == 400

    def test_risk_namespace_rejected(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)
        api_client.force_authenticate(member)
        resp = api_client.post(_tags_url(ws, finding), {"add": ["risk:accepted"]}, format="json")
        assert resp.status_code == 400
        assert resp.data["error"] == "reserved_tag"

    def test_apply_system_tag_by_name_rejected(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)
        Tag.objects.create(workspace=ws, name="platform", slug="platform", kind="system")
        api_client.force_authenticate(member)
        resp = api_client.post(_tags_url(ws, finding), {"add": ["platform"]}, format="json")
        assert resp.status_code == 400
        assert resp.data["error"] == "reserved_tag"

    def test_per_finding_cap_is_400(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        finding = _finding(ws)
        # Seed 50 edges directly (fast path) — the cap check reads the join.
        tags = [Tag.objects.create(workspace=ws, name=f"t{i}", slug=f"t{i}") for i in range(50)]
        FindingTag.objects.bulk_create([FindingTag(workspace=ws, finding=finding, tag=tag) for tag in tags])
        api_client.force_authenticate(member)
        resp = api_client.post(_tags_url(ws, finding), {"add": ["one-more"]}, format="json")
        assert resp.status_code == 400
        assert resp.data["error"] == "tag_limit_exceeded"

    def test_cross_workspace_finding_is_404(self, api_client, workspace_factory, user_factory):
        ws_a, ws_b = workspace_factory(), workspace_factory()
        finding_b = _finding(ws_b)
        api_client.force_authenticate(_member(ws_a, user_factory))
        resp = api_client.post(_tags_url(ws_a, finding_b), {"add": ["env:prod"]}, format="json")
        assert resp.status_code == 404

    def test_non_member_forbidden(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        finding = _finding(ws)
        api_client.force_authenticate(user_factory())
        assert api_client.post(_tags_url(ws, finding), {"add": ["x"]}, format="json").status_code == 403


class TestFindingTagFilter:
    """D7: AND across ``tag`` params, OR within a comma group, ``exclude_tag`` negation —
    inside the EXISTING ranked read."""

    @pytest.fixture()
    def setup(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        api_client.force_authenticate(member)
        f_prod = _finding(ws)
        f_staging = _finding(ws)
        f_prod_pay = _finding(ws)
        api_client.post(_tags_url(ws, f_prod), {"add": ["env:prod"]}, format="json")
        api_client.post(_tags_url(ws, f_staging), {"add": ["env:staging"]}, format="json")
        api_client.post(_tags_url(ws, f_prod_pay), {"add": ["env:prod", "team:payments"]}, format="json")
        return ws, f_prod, f_staging, f_prod_pay

    def _ids(self, api_client, ws, query):
        resp = api_client.get(_list_url(ws) + query)
        assert resp.status_code == 200, resp.data
        return {f["id"] for f in resp.data["data"]["items"]}, resp.data["data"]["total"]

    def test_single_tag(self, api_client, setup):
        ws, f_prod, _, f_prod_pay = setup
        ids, total = self._ids(api_client, ws, "?tag=env:prod")
        assert ids == {str(f_prod.id), str(f_prod_pay.id)}
        assert total == 2

    def test_or_within_group(self, api_client, setup):
        ws, f_prod, f_staging, f_prod_pay = setup
        ids, _ = self._ids(api_client, ws, "?tag=env:prod,env:staging")
        assert ids == {str(f_prod.id), str(f_staging.id), str(f_prod_pay.id)}

    def test_and_across_groups(self, api_client, setup):
        ws, _, _, f_prod_pay = setup
        ids, total = self._ids(api_client, ws, "?tag=env:prod,env:staging&tag=team:payments")
        assert ids == {str(f_prod_pay.id)}
        assert total == 1

    def test_exclude_tag(self, api_client, setup):
        ws, f_prod, f_staging, _ = setup
        ids, _ = self._ids(api_client, ws, "?exclude_tag=team:payments")
        assert ids == {str(f_prod.id), str(f_staging.id)}

    def test_tag_and_exclude_combined(self, api_client, setup):
        ws, f_prod, _, _ = setup
        ids, _ = self._ids(api_client, ws, "?tag=env:prod&exclude_tag=team:payments")
        assert ids == {str(f_prod.id)}

    def test_unknown_slug_group_matches_nothing(self, api_client, setup):
        ws, *_ = setup
        ids, total = self._ids(api_client, ws, "?tag=no-such-tag")
        assert ids == set()
        assert total == 0

    def test_unknown_exclude_is_noop(self, api_client, setup):
        ws, *_ = setup
        ids, _ = self._ids(api_client, ws, "?exclude_tag=no-such-tag")
        assert len(ids) == 3

    def test_soft_deleted_tag_leaves_filter_and_chips(self, api_client, setup):
        ws, f_prod, _, f_prod_pay = setup
        Tag.objects.filter(workspace=ws, slug="env:prod").update(is_deleted=True)
        # Filter: a dead slug resolves to nothing → strict zero results (D7).
        ids, total = self._ids(api_client, ws, "?tag=env:prod")
        assert total == 0
        # Chips: the edge survives, but the dead tag no longer renders (D5).
        resp = api_client.get(_list_url(ws))
        by_id = {f["id"]: f for f in resp.data["data"]["items"]}
        assert [t["slug"] for t in by_id[str(f_prod_pay.id)]["tags"]] == ["team:payments"]
        assert by_id[str(f_prod.id)]["tags"] == []
        assert FindingTag.objects.filter(finding=f_prod).count() == 1  # edge retained

    def test_list_rows_carry_tag_chips(self, api_client, setup):
        ws, _, _, f_prod_pay = setup
        resp = api_client.get(_list_url(ws))
        row = next(f for f in resp.data["data"]["items"] if f["id"] == str(f_prod_pay.id))
        assert [t["slug"] for t in row["tags"]] == ["env:prod", "team:payments"]
        assert all({"id", "slug", "name", "color"} <= set(t) for t in row["tags"])
