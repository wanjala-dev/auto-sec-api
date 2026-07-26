"""Unit tests for the cloud asset graph entities + value objects (no DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.domain.value_objects.enums import AssetRelation, Exposure

pytestmark = [pytest.mark.unit]

_NOW = datetime(2026, 7, 26, tzinfo=UTC)


def _asset(**over):
    base = dict(
        id=uuid4(),
        workspace_id=uuid4(),
        provider="aws",
        arn="arn:aws:ec2:us-east-1:1:instance/i-1",
        asset_urn="arn:aws:ec2:us-east-1:1:instance/i-1",
        resource_type="aws_ec2_instance",
        exposure=Exposure.PUBLIC,
        first_seen_at=_NOW,
        last_seen_at=_NOW,
    )
    base.update(over)
    return CloudAssetEntity(**base)


class TestCloudAssetEntity:
    def test_valid_public_asset(self):
        assert _asset().is_public is True
        assert _asset(exposure=Exposure.PRIVATE).is_public is False

    @pytest.mark.parametrize("field", ["arn", "asset_urn", "resource_type"])
    def test_required_fields(self, field):
        with pytest.raises(ValueError):
            _asset(**{field: ""})


class TestExposure:
    def test_from_value_normalizes_and_defaults_private(self):
        assert Exposure.from_value("PUBLIC ") is Exposure.PUBLIC
        assert Exposure.from_value("internal") is Exposure.INTERNAL
        assert Exposure.from_value("nonsense") is Exposure.PRIVATE
        assert Exposure.from_value(None) is Exposure.PRIVATE


class TestCloudAssetEdgeEntity:
    def test_self_loop_rejected(self):
        same = uuid4()
        with pytest.raises(ValueError):
            CloudAssetEdgeEntity(
                id=uuid4(),
                workspace_id=uuid4(),
                src_asset_id=same,
                dst_asset_id=same,
                relation=AssetRelation.ATTACHED_TO,
                last_seen_at=_NOW,
            )

    def test_valid_edge(self):
        edge = CloudAssetEdgeEntity(
            id=uuid4(),
            workspace_id=uuid4(),
            src_asset_id=uuid4(),
            dst_asset_id=uuid4(),
            relation=AssetRelation.CAN_ASSUME,
            last_seen_at=_NOW,
        )
        assert edge.relation is AssetRelation.CAN_ASSUME

    def test_relation_from_value(self):
        assert AssetRelation.from_value("allows_ingress_from") is AssetRelation.ALLOWS_INGRESS_FROM
