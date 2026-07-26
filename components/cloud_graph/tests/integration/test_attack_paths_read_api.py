"""Read API over materialised attack paths — GET /cloud-graph/workspaces/<ws>/attack-paths/."""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone

from components.cloud_graph.application.use_cases.materialize_attack_paths_use_case import (
    MaterializeAttackPathsUseCase,
)
from components.cloud_graph.domain.services.attack_path_analyzer import AttackPathAnalyzer
from components.cloud_graph.infrastructure.repositories.django_attack_path_repository import (
    DjangoAttackPathRepository,
)
from components.cloud_graph.infrastructure.repositories.django_cloud_graph_repository import (
    DjangoCloudGraphRepository,
)
from infrastructure.persistence.cloud_graph.models import CloudAsset, CloudAssetEdge
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.django_db]


def _url(ws, query=""):
    return f"/api/v1/cloud-graph/workspaces/{ws.id}/attack-paths/{query}"


def _member(ws, user_factory):
    member = user_factory()
    WorkspaceMembership.objects.create(workspace=ws, user=member, role="member", status="active")
    return member


def _asset(ws, arn, rtype, exposure, name):
    now = timezone.now()
    return CloudAsset.objects.create(
        id=uuid.uuid4(),
        workspace=ws,
        arn=arn,
        asset_urn=f"urn:{rtype}:{arn}",
        resource_type=rtype,
        region="us-east-1",
        name=name,
        exposure=exposure,
        first_seen_at=now,
        last_seen_at=now,
    )


def _materialize_toxic(ws):
    ec2 = _asset(ws, "arn:ec2:web", "aws_ec2_instance", "public", "web-frontend")
    role = _asset(ws, "arn:iam:role", "aws_iam_role", "private", "app-exec-role")
    admin = _asset(ws, "arn:iam:admin", "aws_iam_policy", "private", "AdministratorAccess")
    data = _asset(ws, "arn:s3:data", "aws_s3_bucket", "internal", "customer-data")
    for s, d, r in [(ec2, role, "can_assume"), (role, admin, "has_policy"), (role, data, "reads_bucket")]:
        CloudAssetEdge.objects.create(
            id=uuid.uuid4(), workspace=ws, src_asset=s, dst_asset=d, relation=r, last_seen_at=timezone.now()
        )
    MaterializeAttackPathsUseCase(
        asset_store=DjangoCloudGraphRepository(),
        path_store=DjangoAttackPathRepository(),
        analyzer=AttackPathAnalyzer(),
        publisher=None,
    ).execute(ws.id, timezone.now())


class TestAttackPathsReadApi:
    def test_lists_ranked_paths(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        _materialize_toxic(ws)

        api_client.force_authenticate(member)
        resp = api_client.get(_url(ws))

        assert resp.status_code == 200, resp.data
        data = resp.data["data"]
        assert data["total"] == 2
        top = data["items"][0]
        assert top["category"] == "public_compute_admin"
        assert top["severity"] == "critical"
        assert top["risk_band"] == "red"
        assert top["risk_score"] >= data["items"][1]["risk_score"]  # ranked
        assert top["entry"]["label"] == "web-frontend"
        assert top["target"]["label"] == "AdministratorAccess"
        assert [leg["relation"] for leg in top["legs"]] == ["can_assume", "has_policy"]

    def test_filters_by_category(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        _materialize_toxic(ws)

        api_client.force_authenticate(member)
        data = api_client.get(_url(ws, "?category=public_data_exposure")).data["data"]
        assert data["total"] == 1
        assert data["items"][0]["category"] == "public_data_exposure"

    def test_filters_by_min_score(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        _materialize_toxic(ws)

        api_client.force_authenticate(member)
        data = api_client.get(_url(ws, "?min_score=90")).data["data"]
        assert data["total"] == 1  # only the critical admin path clears 90
        assert data["items"][0]["category"] == "public_compute_admin"

    def test_empty_when_not_materialized(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        api_client.force_authenticate(member)
        data = api_client.get(_url(ws)).data["data"]
        assert data == {"items": [], "total": 0}

    def test_non_member_forbidden(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        _materialize_toxic(ws)
        api_client.force_authenticate(user_factory())
        assert api_client.get(_url(ws)).status_code == 403

    def test_requires_authentication(self, api_client, workspace_factory):
        ws = workspace_factory()
        assert api_client.get(_url(ws)).status_code in (401, 403)

    def test_invalid_category_is_400(self, api_client, workspace_factory, user_factory):
        ws = workspace_factory()
        member = _member(ws, user_factory)
        api_client.force_authenticate(member)
        assert api_client.get(_url(ws, "?category=nonsense")).status_code == 400
