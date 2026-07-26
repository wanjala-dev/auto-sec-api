"""Integration: the cloud_graph store — idempotent upserts, first_seen, filters, scope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.domain.value_objects.enums import AssetRelation, Exposure

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def _asset(
    ws,
    *,
    arn="arn:aws:ec2:us-east-1:1:instance/i-1",
    exposure=Exposure.PUBLIC,
    resource_type="aws_ec2_instance",
    seen=None,
    first=None,
):
    now = seen or _NOW
    return CloudAssetEntity(
        id=uuid4(),
        workspace_id=ws.id,
        provider="aws",
        arn=arn,
        asset_urn=arn,
        resource_type=resource_type,
        exposure=exposure,
        first_seen_at=first or now,
        last_seen_at=now,
        region="us-east-1",
        name="i-1",
    )


class TestCloudGraphRepository:
    def test_upsert_asset_is_idempotent_and_preserves_first_seen(self, workspace_factory):
        ws = workspace_factory()
        store = CloudGraphProvider.build_cloud_asset_store()
        old = _NOW - timedelta(days=2)
        first = store.upsert_asset(_asset(ws, seen=old, first=old, exposure=Exposure.PRIVATE))
        # Re-sync the same ARN later, now public — must update in place, not duplicate.
        again = store.upsert_asset(_asset(ws, seen=_NOW, exposure=Exposure.PUBLIC))

        from infrastructure.persistence.cloud_graph.models import CloudAsset

        assert CloudAsset.objects.filter(workspace=ws).count() == 1
        assert again.id == first.id
        assert again.exposure is Exposure.PUBLIC  # config updated
        assert again.first_seen_at == old  # first_seen preserved
        assert again.last_seen_at == _NOW  # last_seen advanced

    def test_upsert_edge_is_idempotent(self, workspace_factory):
        ws = workspace_factory()
        store = CloudGraphProvider.build_cloud_asset_store()
        a = store.upsert_asset(_asset(ws, arn="arn:ec2:i-1"))
        b = store.upsert_asset(_asset(ws, arn="arn:iam:role-1", resource_type="aws_iam_role"))

        def _edge():
            return CloudAssetEdgeEntity(
                id=uuid4(),
                workspace_id=ws.id,
                src_asset_id=a.id,
                dst_asset_id=b.id,
                relation=AssetRelation.ATTACHED_TO,
                last_seen_at=_NOW,
            )

        store.upsert_edge(_edge())
        store.upsert_edge(_edge())  # same (src, dst, relation) → no duplicate

        from infrastructure.persistence.cloud_graph.models import CloudAssetEdge

        assert CloudAssetEdge.objects.filter(workspace=ws).count() == 1
        edges = store.list_edges_from(ws.id, a.id)
        assert len(edges) == 1
        assert edges[0].relation is AssetRelation.ATTACHED_TO
        assert edges[0].dst_asset_id == b.id

    def test_list_assets_filters_and_is_workspace_scoped(self, workspace_factory):
        ws = workspace_factory()
        other = workspace_factory()
        store = CloudGraphProvider.build_cloud_asset_store()
        store.upsert_asset(_asset(ws, arn="arn:ec2:1", resource_type="aws_ec2_instance", exposure=Exposure.PUBLIC))
        store.upsert_asset(_asset(ws, arn="arn:s3:1", resource_type="aws_s3_bucket", exposure=Exposure.PRIVATE))
        store.upsert_asset(_asset(other, arn="arn:ec2:x"))

        assert len(store.list_assets(ws.id)) == 2
        assert len(store.list_assets(ws.id, resource_type="aws_s3_bucket")) == 1
        assert len(store.list_assets(ws.id, exposure="public")) == 1
        assert all(a.workspace_id == ws.id for a in store.list_assets(ws.id))

    def test_get_asset_by_arn_roundtrips(self, workspace_factory):
        ws = workspace_factory()
        store = CloudGraphProvider.build_cloud_asset_store()
        store.upsert_asset(_asset(ws, arn="arn:ec2:rt", exposure=Exposure.PUBLIC))

        got = store.get_asset_by_arn(ws.id, "arn:ec2:rt")
        assert got is not None
        assert got.arn == "arn:ec2:rt"
        assert got.exposure is Exposure.PUBLIC
        assert got.resource_type == "aws_ec2_instance"
        assert store.get_asset_by_arn(ws.id, "arn:missing") is None
