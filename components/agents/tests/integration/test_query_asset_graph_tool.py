"""The query_asset_graph triage tool — grounds blast-radius from the asset graph."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from components.agents.infrastructure.adapters.langchain.tools.asset_graph import query_asset_graph
from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.domain.value_objects.enums import Exposure

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


class _StubAgent:
    """The tool only needs ``workspace_id`` off the agent."""

    def __init__(self, workspace_id):
        self.workspace_id = workspace_id


def _seed_asset(
    ws,
    *,
    arn,
    resource_type="aws_s3_bucket",
    exposure=Exposure.PUBLIC,
    region="us-east-1",
    account="123456789012",
    service="s3",
    name="res",
):
    CloudGraphProvider.build_cloud_asset_store().upsert_asset(
        CloudAssetEntity(
            id=uuid4(),
            workspace_id=ws.id,
            provider="aws",
            arn=arn,
            asset_urn=arn,
            resource_type=resource_type,
            exposure=exposure,
            first_seen_at=_NOW,
            last_seen_at=_NOW,
            region=region,
            name=name,
            attributes={"account_id": account, "service": service},
        )
    )


class TestQueryAssetGraphTool:
    def test_exact_arn_lookup_returns_real_exposure(self, workspace_factory):
        ws = workspace_factory()
        _seed_asset(ws, arn="arn:aws:s3:::bucket-a", exposure=Exposure.PUBLIC)

        out = json.loads(query_asset_graph(_StubAgent(ws.id), "arn:aws:s3:::bucket-a"))
        assert out["total"] == 1
        asset = out["assets"][0]
        assert asset["arn"] == "arn:aws:s3:::bucket-a"
        assert asset["exposure"] == "public"
        assert asset["resource_type"] == "aws_s3_bucket"
        assert asset["account_id"] == "123456789012"

    def test_service_or_type_search(self, workspace_factory):
        ws = workspace_factory()
        _seed_asset(ws, arn="arn:aws:ec2:us-east-1:1:instance/i-1", resource_type="aws_ec2_instance", service="ec2")
        _seed_asset(ws, arn="arn:aws:s3:::b", resource_type="aws_s3_bucket", service="s3")

        out = json.loads(query_asset_graph(_StubAgent(ws.id), "ec2"))
        assert out["total"] == 1
        assert out["assets"][0]["resource_type"] == "aws_ec2_instance"

    def test_json_wrapper_input_is_tolerated(self, workspace_factory):
        ws = workspace_factory()
        _seed_asset(ws, arn="arn:aws:s3:::wrapped")

        out = json.loads(query_asset_graph(_StubAgent(ws.id), '{"arn": "arn:aws:s3:::wrapped"}'))
        assert out["total"] == 1

    def test_empty_graph_returns_a_helpful_note(self, workspace_factory):
        ws = workspace_factory()
        out = json.loads(query_asset_graph(_StubAgent(ws.id), "arn:aws:s3:::nope"))
        assert out["assets"] == []
        assert "note" in out

    def test_is_workspace_scoped(self, workspace_factory):
        ws = workspace_factory()
        other = workspace_factory()
        _seed_asset(other, arn="arn:aws:s3:::theirs")

        out = json.loads(query_asset_graph(_StubAgent(ws.id), "arn:aws:s3:::theirs"))
        assert out["assets"] == []
