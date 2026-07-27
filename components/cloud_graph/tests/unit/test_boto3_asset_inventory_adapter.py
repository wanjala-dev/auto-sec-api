"""boto3 collector — node/edge production + it feeds the real attack-path analyzer.

Mocks boto3 (EC2 describe_instances, IAM get_instance_profile + list_attached_role_policies)
via a stubbed ``_client``. The clinching test runs the collected nodes+edges through the
REAL ``AttackPathAnalyzer`` and asserts a ``PUBLIC_COMPUTE_ADMIN`` path falls out — the
whole point of the collector.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from components.cloud_graph.domain.services.attack_path_analyzer import AttackPathAnalyzer
from components.cloud_graph.domain.value_objects.attack_path import AttackPathCategory
from components.cloud_graph.domain.value_objects.enums import AssetRelation, Exposure
from components.cloud_graph.infrastructure.adapters.boto3_asset_inventory_adapter import (
    Boto3AssetInventoryAdapter,
)
from components.integrations.application.ports.aws_account_access_port import AwsAccountRef

pytestmark = pytest.mark.unit

_ACCOUNT = "123456789012"
_PROFILE_ARN = f"arn:aws:iam::{_ACCOUNT}:instance-profile/web-profile"
_ROLE_ARN = f"arn:aws:iam::{_ACCOUNT}:role/web-role"
_ADMIN_POLICY_ARN = "arn:aws:iam::aws:policy/AdministratorAccess"


class _Paginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **kwargs):
        yield from self._pages


class _FakeEc2:
    def __init__(self, instances):
        self._instances = instances

    def get_paginator(self, name):
        assert name == "describe_instances"
        return _Paginator([{"Reservations": [{"Instances": self._instances}]}])


class _FakeIam:
    def __init__(self, *, roles_by_profile, policies_by_role):
        self._roles_by_profile = roles_by_profile
        self._policies_by_role = policies_by_role

    def get_instance_profile(self, InstanceProfileName):
        return {"InstanceProfile": {"Roles": self._roles_by_profile.get(InstanceProfileName, [])}}

    def get_paginator(self, name):
        assert name == "list_attached_role_policies"
        outer = self

        class _P:
            def paginate(self, RoleName):
                yield {"AttachedPolicies": outer._policies_by_role.get(RoleName, [])}

        return _P()


class _FakeAccess:
    def accounts_for(self, workspace_id):
        return [AwsAccountRef(account_id=_ACCOUNT, regions=("us-east-1",))]

    def credentials_for(self, **kwargs):
        return {"AccessKeyId": "AK", "SecretAccessKey": "SK", "SessionToken": "ST"}


class _FakeStore:
    """Duck-typed CloudAssetStorePort — records upserts, stable id per ARN."""

    def __init__(self):
        self.assets: dict[str, object] = {}
        self.edges: dict[tuple, object] = {}

    def upsert_asset(self, asset):
        existing = self.assets.get(asset.arn)
        stored = asset if existing is None else _replace_id(asset, existing.id)
        self.assets[asset.arn] = stored
        return stored

    def upsert_edge(self, edge):
        self.edges[(edge.src_asset_id, edge.dst_asset_id, edge.relation)] = edge
        return edge


def _replace_id(asset, id_):
    import dataclasses

    return dataclasses.replace(asset, id=id_)


def _stub_adapter(*, instances, roles_by_profile, policies_by_role):
    fake_ec2 = _FakeEc2(instances)
    fake_iam = _FakeIam(roles_by_profile=roles_by_profile, policies_by_role=policies_by_role)

    class _Stub(Boto3AssetInventoryAdapter):
        def _client(self, service, creds, region):
            return fake_ec2 if service == "ec2" else fake_iam

    store = _FakeStore()
    return _Stub(asset_store=store, access_port=_FakeAccess()), store


def _public_admin_scenario():
    instances = [
        {
            "InstanceId": "i-abc",
            "PublicIpAddress": "203.0.113.5",
            "Tags": [{"Key": "Name", "Value": "web-frontend"}],
            "IamInstanceProfile": {"Arn": _PROFILE_ARN},
            "State": {"Name": "running"},
        }
    ]
    return _stub_adapter(
        instances=instances,
        roles_by_profile={"web-profile": [{"Arn": _ROLE_ARN, "RoleName": "web-role"}]},
        policies_by_role={"web-role": [{"PolicyName": "AdministratorAccess", "PolicyArn": _ADMIN_POLICY_ARN}]},
    )


class TestCollection:
    def test_produces_instance_role_policy_nodes_and_edges(self):
        adapter, store = _public_admin_scenario()
        result = adapter.sync_workspace(uuid.uuid4())

        assert result.assets_upserted == 3
        instance = store.assets[f"arn:aws:ec2:us-east-1:{_ACCOUNT}:instance/i-abc"]
        assert instance.exposure is Exposure.PUBLIC
        assert instance.resource_type == "aws_ec2_instance"
        assert instance.name == "web-frontend"
        assert store.assets[_ROLE_ARN].resource_type == "aws_iam_role"
        assert store.assets[_ADMIN_POLICY_ARN].resource_type == "aws_iam_policy"

        relations = {(e.relation) for e in store.edges.values()}
        assert AssetRelation.ATTACHED_TO in relations
        assert AssetRelation.HAS_POLICY in relations
        assert len(store.edges) == 2

    def test_private_instance_without_profile_yields_no_edges(self):
        adapter, store = _stub_adapter(
            instances=[{"InstanceId": "i-priv", "Tags": [], "State": {"Name": "running"}}],
            roles_by_profile={},
            policies_by_role={},
        )
        adapter.sync_workspace(uuid.uuid4())
        node = store.assets[f"arn:aws:ec2:us-east-1:{_ACCOUNT}:instance/i-priv"]
        assert node.exposure is Exposure.PRIVATE
        assert store.edges == {}


class TestFeedsAnalyzer:
    def test_collected_graph_yields_public_compute_admin_path(self):
        adapter, store = _public_admin_scenario()
        ws = uuid.uuid4()
        adapter.sync_workspace(ws)

        assets = list(store.assets.values())
        edges = list(store.edges.values())
        paths = AttackPathAnalyzer().analyze(assets, edges, workspace_id=ws, now=datetime.now(UTC))

        assert any(p.category is AttackPathCategory.PUBLIC_COMPUTE_ADMIN for p in paths)
