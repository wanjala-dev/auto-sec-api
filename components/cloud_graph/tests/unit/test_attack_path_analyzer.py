"""Unit tests for AttackPathAnalyzer — the toxic-combination correlation (no DB)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from components.cloud_graph.domain.entities.cloud_asset_edge_entity import CloudAssetEdgeEntity
from components.cloud_graph.domain.entities.cloud_asset_entity import CloudAssetEntity
from components.cloud_graph.domain.services.attack_path_analyzer import AttackPathAnalyzer
from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory
from components.cloud_graph.domain.value_objects.enums import AssetRelation, Exposure
from components.shared_kernel.domain.security import Severity

pytestmark = [pytest.mark.unit]

WS = uuid.uuid4()
NOW = datetime(2026, 7, 26, tzinfo=UTC)


def _asset(name, rtype, exposure=Exposure.PRIVATE):
    aid = uuid.uuid4()
    return CloudAssetEntity(
        id=aid,
        workspace_id=WS,
        provider="aws",
        arn=f"arn:aws:{rtype}:{name}",
        asset_urn=f"urn:{rtype}:{name}",
        resource_type=rtype,
        exposure=exposure,
        first_seen_at=NOW,
        last_seen_at=NOW,
        name=name,
    )


def _edge(src, dst, relation):
    return CloudAssetEdgeEntity(
        id=uuid.uuid4(),
        workspace_id=WS,
        src_asset_id=src.id,
        dst_asset_id=dst.id,
        relation=relation,
        last_seen_at=NOW,
    )


def _toxic_graph():
    """public EC2 -can_assume-> role -has_policy-> AdministratorAccess ; role -reads_bucket-> data."""
    ec2 = _asset("web-frontend", "aws_ec2_instance", Exposure.PUBLIC)
    role = _asset("app-exec-role", "aws_iam_role")
    admin = _asset("AdministratorAccess", "aws_iam_policy")
    data = _asset("customer-data", "aws_s3_bucket", Exposure.INTERNAL)
    assets = [ec2, role, admin, data]
    edges = [
        _edge(ec2, role, AssetRelation.CAN_ASSUME),
        _edge(role, admin, AssetRelation.HAS_POLICY),
        _edge(role, data, AssetRelation.READS_BUCKET),
    ]
    return assets, edges, ec2, admin, data


class TestAttackPathAnalyzer:
    def test_finds_admin_and_data_paths_ranked_admin_first(self):
        assets, edges, ec2, admin, data = _toxic_graph()
        paths = AttackPathAnalyzer().analyze(assets, edges, workspace_id=WS, now=NOW)

        assert len(paths) == 2
        # admin path outranks the data path
        assert paths[0].category is AttackPathCategory.PUBLIC_COMPUTE_ADMIN
        assert paths[0].target_asset_id == admin.id
        assert paths[1].category is AttackPathCategory.PUBLIC_DATA_EXPOSURE
        assert paths[0].risk_score > paths[1].risk_score
        assert paths[0].entry_asset_id == ec2.id

    def test_admin_path_is_critical_with_full_chain(self):
        assets, edges, ec2, admin, data = _toxic_graph()
        top = AttackPathAnalyzer().analyze(assets, edges, workspace_id=WS, now=NOW)[0]
        # base 80 + direct(<=2) 8 + full-admin 7 = 95
        assert top.risk_score == pytest.approx(95.0)
        assert top.severity is Severity.CRITICAL
        assert top.length == 2
        assert [leg.relation for leg in top.legs] == ["can_assume", "has_policy"]
        assert top.asset_urns == (ec2.asset_urn, "urn:aws_iam_role:app-exec-role", admin.asset_urn)

    def test_no_path_when_entry_is_not_public(self):
        assets, edges, ec2, admin, data = _toxic_graph()
        # demote the only public workload to private → no exposed entry → no paths
        private_assets = [(a if a.id != ec2.id else _private_copy(a)) for a in assets]
        paths = AttackPathAnalyzer().analyze(private_assets, edges, workspace_id=WS, now=NOW)
        assert paths == []

    def test_ignores_edges_to_missing_nodes(self):
        assets, edges, ec2, admin, data = _toxic_graph()
        ghost = _edge(ec2, _asset("ghost", "aws_iam_role"), AssetRelation.CAN_ASSUME)  # dst not in assets
        paths = AttackPathAnalyzer().analyze(assets, [*edges, ghost], workspace_id=WS, now=NOW)
        assert len(paths) == 2  # ghost edge dropped, real paths unaffected

    def test_path_id_is_stable_across_runs(self):
        assets, edges, *_ = _toxic_graph()
        a = AttackPathAnalyzer().analyze(assets, edges, workspace_id=WS, now=NOW)
        b = AttackPathAnalyzer().analyze(assets, edges, workspace_id=WS, now=NOW)
        assert [p.id for p in a] == [p.id for p in b]  # deterministic uuid5, no churn


def _private_copy(asset):
    import dataclasses

    return dataclasses.replace(asset, exposure=Exposure.PRIVATE)
