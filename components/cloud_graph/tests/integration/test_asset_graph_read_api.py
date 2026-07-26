"""Read API over the cloud asset graph — GET /api/v1/cloud-graph/workspaces/<ws>/graph/.

Pins the surface the HUD Asset Graph panel renders: membership-gated, workspace-scoped,
filterable (exposure/resource_type), node-capped, with only the edges whose BOTH
endpoints are in the returned node set (a dangling edge would break the client layout).
"""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from infrastructure.persistence.cloud_graph.models import CloudAsset, CloudAssetEdge
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.django_db]


def _url(ws, query=""):
    return f"/api/v1/cloud-graph/workspaces/{ws.id}/graph/{query}"


def _member(ws, user_factory):
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    return member


def _asset(ws, *, arn, resource_type="aws_ec2_instance", exposure="private", name="", attributes=None):
    now = timezone.now()
    return CloudAsset.objects.create(
        id=uuid.uuid4(),
        workspace=ws,
        arn=arn,
        asset_urn=f"urn:{resource_type}:{arn}",
        resource_type=resource_type,
        region="us-east-1",
        name=name,
        exposure=exposure,
        attributes=attributes or {"account_id": "111", "service": "ec2"},
        first_seen_at=now,
        last_seen_at=now,
    )


def _edge(ws, src, dst, relation="attached_to"):
    return CloudAssetEdge.objects.create(
        id=uuid.uuid4(),
        workspace=ws,
        src_asset=src,
        dst_asset=dst,
        relation=relation,
        last_seen_at=timezone.now(),
    )


class TestAssetGraphReadApi:
    def test_returns_nodes_and_edges(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        ec2 = _asset(ws, arn="arn:aws:ec2:...:i-1", exposure="public", name="web")
        role = _asset(ws, arn="arn:aws:iam:...:role/app", resource_type="aws_iam_role")
        _edge(ws, ec2, role, relation="can_assume")

        api_client.force_authenticate(member)
        resp = api_client.get(_url(ws))

        assert resp.status_code == 200, resp.data
        data = resp.data["data"]
        assert data["total_nodes"] == 2
        assert {n["arn"] for n in data["nodes"]} == {ec2.arn, role.arn}
        pub = next(n for n in data["nodes"] if n["arn"] == ec2.arn)
        assert pub["exposure"] == "public" and pub["is_public"] is True
        assert pub["name"] == "web" and pub["service"] == "ec2"
        assert len(data["edges"]) == 1
        e = data["edges"][0]
        assert e["source"] == str(ec2.id) and e["target"] == str(role.id)
        assert e["relation"] == "can_assume"

    def test_excludes_edges_with_endpoint_outside_node_set(self, api_client, workspace_factory, user_factory):
        # exposure=public returns only the ec2 node; the ec2->role edge must be dropped
        # (role isn't in the node set) so the client never gets a dangling edge.
        ws = workspace_factory()
        member = _member(ws, user_factory)
        ec2 = _asset(ws, arn="arn:aws:ec2:...:i-1", exposure="public")
        role = _asset(ws, arn="arn:aws:iam:...:role/app", resource_type="aws_iam_role", exposure="private")
        _edge(ws, ec2, role)

        api_client.force_authenticate(member)
        data = api_client.get(_url(ws, "?exposure=public")).data["data"]
        assert {n["arn"] for n in data["nodes"]} == {ec2.arn}
        assert data["edges"] == []

    def test_filters_by_resource_type(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        _asset(ws, arn="arn:aws:ec2:...:i-1", resource_type="aws_ec2_instance")
        _asset(ws, arn="arn:aws:s3:::b", resource_type="aws_s3_bucket")

        api_client.force_authenticate(member)
        data = api_client.get(_url(ws, "?resource_type=aws_s3_bucket")).data["data"]
        assert {n["resource_type"] for n in data["nodes"]} == {"aws_s3_bucket"}

    def test_caps_nodes_by_limit(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        for i in range(5):
            _asset(ws, arn=f"arn:aws:ec2:...:i-{i}")

        api_client.force_authenticate(member)
        data = api_client.get(_url(ws, "?limit=2")).data["data"]
        assert data["total_nodes"] == 2
        assert len(data["nodes"]) == 2

    def test_scoped_to_workspace(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        other = workspace_factory()
        member = _member(ws, user_factory)
        _asset(ws, arn="arn:mine")
        _asset(other, arn="arn:theirs")

        api_client.force_authenticate(member)
        data = api_client.get(_url(ws)).data["data"]
        assert {n["arn"] for n in data["nodes"]} == {"arn:mine"}

    def test_non_member_forbidden(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        _asset(ws, arn="arn:x")
        api_client.force_authenticate(user_factory())  # authenticated but not a member
        assert api_client.get(_url(ws)).status_code == 403

    def test_requires_authentication(self, api_client, workspace_factory):
        ws = workspace_factory()
        assert api_client.get(_url(ws)).status_code in (401, 403)

    def test_invalid_exposure_is_400(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        api_client.force_authenticate(member)
        assert api_client.get(_url(ws, "?exposure=exposed")).status_code == 400

    def test_query_count_is_constant_wrt_rows(self, api_client, workspace_factory, user_factory):
        # No N+1 (performance rule §1): the graph read is a fixed number of queries
        # (membership + list_assets + list_all_edges) regardless of node/edge count.
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        ws = workspace_factory()
        member = _member(ws, user_factory)
        api_client.force_authenticate(member)
        api_client.get(_url(ws))  # warm one-time caches

        a = _asset(ws, arn="arn:a")
        b = _asset(ws, arn="arn:b")
        _edge(ws, a, b)
        with CaptureQueriesContext(connection) as few:
            api_client.get(_url(ws))

        prev = b
        for i in range(10):
            nxt = _asset(ws, arn=f"arn:bulk-{i}")
            _edge(ws, prev, nxt)
            prev = nxt
        with CaptureQueriesContext(connection) as many:
            api_client.get(_url(ws))

        assert len(many.captured_queries) == len(few.captured_queries), [q["sql"] for q in many.captured_queries]
