"""The boto3 inventory adapter builds the toxic-path graph the analyzer needs.

Fakes the AWS clients (no network, no creds) + the account-access port, runs the adapter
against the real asset store, then materializes attack paths — asserting a public EC2
instance whose instance-profile role carries AdministratorAccess yields a real
PUBLIC_COMPUTE_ADMIN path. Also unit-tests the policy-document analysis.
"""

from __future__ import annotations

import pytest

from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
from components.cloud_graph.infrastructure.adapters.boto3_inventory_adapter import (
    Boto3InventoryAdapter,
    _analyze_policy,
)

_ACCOUNT = "111122223333"


class _Paginator:
    def __init__(self, pages):
        self._pages = pages

    def paginate(self, **_):
        return iter(self._pages)


class _FakeEc2:
    """A public instance in a public subnet (route → IGW) behind an open SG, plus an
    optional closed-SG variant to prove reachability gating."""

    def __init__(self, sg_open=True, regions=None, describe_regions_error=False):
        self._sg_open = sg_open
        self._regions = regions
        self._describe_regions_error = describe_regions_error

    def describe_regions(self):
        if self._describe_regions_error:
            raise RuntimeError("AccessDenied: ec2:DescribeRegions")
        return {"Regions": [{"RegionName": r} for r in (self._regions or ["us-east-1"])]}

    def get_paginator(self, name):
        if name == "describe_instances":
            return _Paginator(
                [
                    {
                        "Reservations": [
                            {
                                "Instances": [
                                    {
                                        "InstanceId": "i-0abc",
                                        "PublicIpAddress": "203.0.113.7",
                                        "SubnetId": "subnet-pub",
                                        "SecurityGroups": [{"GroupId": "sg-web"}],
                                        "IamInstanceProfile": {"Arn": f"arn:aws:iam::{_ACCOUNT}:instance-profile/app"},
                                        "Tags": [{"Key": "Name", "Value": "web"}],
                                    }
                                ]
                            }
                        ]
                    }
                ]
            )
        if name == "describe_internet_gateways":
            return _Paginator(
                [{"InternetGateways": [{"InternetGatewayId": "igw-1", "Attachments": [{"VpcId": "vpc-1"}]}]}]
            )
        if name == "describe_route_tables":
            return _Paginator(
                [
                    {
                        "RouteTables": [
                            {
                                "VpcId": "vpc-1",
                                "Routes": [{"GatewayId": "igw-1", "DestinationCidrBlock": "0.0.0.0/0"}],
                                "Associations": [{"SubnetId": "subnet-pub", "Main": False}],
                            }
                        ]
                    }
                ]
            )
        if name == "describe_subnets":
            return _Paginator([{"Subnets": [{"SubnetId": "subnet-pub", "VpcId": "vpc-1"}]}])
        if name == "describe_security_groups":
            perms = [{"IpRanges": [{"CidrIp": "0.0.0.0/0"}]}] if self._sg_open else [{"IpRanges": []}]
            return _Paginator(
                [{"SecurityGroups": [{"GroupId": "sg-web", "GroupName": "web-sg", "IpPermissions": perms}]}]
            )
        return _Paginator([])


class _FakeIam:
    def get_paginator(self, name):
        if name == "list_instance_profiles":
            return _Paginator(
                [
                    {
                        "InstanceProfiles": [
                            {
                                "Arn": f"arn:aws:iam::{_ACCOUNT}:instance-profile/app",
                                "InstanceProfileName": "app",
                                "Roles": [{"Arn": f"arn:aws:iam::{_ACCOUNT}:role/app-role", "RoleName": "app-role"}],
                            }
                        ]
                    }
                ]
            )
        if name == "list_roles":
            return _Paginator([{"Roles": [{"Arn": f"arn:aws:iam::{_ACCOUNT}:role/app-role", "RoleName": "app-role"}]}])
        return _Paginator([])

    def list_attached_role_policies(self, RoleName):
        return {
            "AttachedPolicies": [
                {"PolicyArn": "arn:aws:iam::aws:policy/AdministratorAccess", "PolicyName": "AdministratorAccess"}
            ]
        }

    def list_role_policies(self, RoleName):
        return {"PolicyNames": []}

    def get_policy(self, PolicyArn):
        return {"Policy": {"DefaultVersionId": "v1"}}

    def get_policy_version(self, PolicyArn, VersionId):
        return {"PolicyVersion": {"Document": {"Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}}}


class _FakeS3:
    def list_buckets(self):
        return {"Buckets": [{"Name": "crown-jewels"}]}


class _FakeSession:
    def __init__(self, sg_open=True, regions=None, describe_regions_error=False):
        self._sg_open = sg_open
        self._regions = regions
        self._describe_regions_error = describe_regions_error

    def client(self, name, region_name=None):
        return {
            "ec2": _FakeEc2(
                sg_open=self._sg_open,
                regions=self._regions,
                describe_regions_error=self._describe_regions_error,
            ),
            "iam": _FakeIam(),
            "s3": _FakeS3(),
        }[name]


class _FakeAccess:
    def accounts_for(self, _workspace_id):
        return [_ACCOUNT]

    def credentials_for(self, **_):
        return {"AccessKeyId": "x", "SecretAccessKey": "y", "SessionToken": "z"}


@pytest.mark.django_db
def test_boto3_adapter_synthesizes_a_public_compute_admin_path(workspace_factory):
    workspace_id = workspace_factory().id
    store = CloudGraphProvider.build_cloud_asset_store()
    adapter = Boto3InventoryAdapter(
        access_port=_FakeAccess(),
        asset_store=store,
        session_factory=lambda _creds: _FakeSession(),
        regions=["us-east-1"],
    )

    result = adapter.sync_workspace(workspace_id)

    # instance + instance-profile + role + admin policy + bucket + subnet + sg + igw
    assert result.assets_upserted >= 7
    # slice-1 edges (ATTACHED_TO/CAN_ASSUME/HAS_POLICY/READS_BUCKET) + topology
    # (IN_SUBNET, ALLOWS_INGRESS_FROM, ROUTES_TO_IGW)
    assert result.edges_upserted >= 6

    # The instance is PUBLIC by REAL reachability — public subnet (route→IGW) + an open SG —
    # so the analyzer walks: public web instance → profile → role → AdministratorAccess.
    from django.utils import timezone

    paths = CloudGraphProvider.build_materialize_attack_paths_use_case().execute(workspace_id, timezone.now())
    assert paths.paths_found >= 1


@pytest.mark.django_db
def test_closed_security_group_makes_the_instance_unreachable(workspace_factory):
    """A public IP behind a CLOSED security group is not internet-reachable — no PUBLIC
    entry, so no attack path. This is the accuracy the topology pass buys over the
    public-IP heuristic."""
    workspace_id = workspace_factory().id
    store = CloudGraphProvider.build_cloud_asset_store()
    adapter = Boto3InventoryAdapter(
        access_port=_FakeAccess(),
        asset_store=store,
        session_factory=lambda _creds: _FakeSession(sg_open=False),
        regions=["us-east-1"],
    )

    adapter.sync_workspace(workspace_id)

    from django.utils import timezone

    paths = CloudGraphProvider.build_materialize_attack_paths_use_case().execute(workspace_id, timezone.now())
    assert paths.paths_found == 0


def test_resolve_regions_auto_discovers_enabled_regions():
    """With no pin, the adapter scans the account's ENABLED regions (describe_regions)."""
    adapter = Boto3InventoryAdapter(access_port=_FakeAccess())
    session = _FakeSession(regions=["us-east-1", "eu-west-1", "ap-southeast-2"])
    assert adapter._resolve_regions(session, _ACCOUNT) == ("us-east-1", "eu-west-1", "ap-southeast-2")


def test_resolve_regions_respects_explicit_pin_without_discovery():
    """An explicit region pin wins verbatim — discovery is skipped (proven: a session that
    would RAISE on describe_regions still returns the pin, never touching it)."""
    adapter = Boto3InventoryAdapter(access_port=_FakeAccess(), regions=["ap-southeast-2"])
    session = _FakeSession(describe_regions_error=True)
    assert adapter._resolve_regions(session, _ACCOUNT) == ("ap-southeast-2",)


def test_resolve_regions_falls_back_when_discovery_denied():
    """describe_regions denied (missing IAM permission) → degrade to us-east-1, not crash."""
    adapter = Boto3InventoryAdapter(access_port=_FakeAccess())
    session = _FakeSession(describe_regions_error=True)
    assert adapter._resolve_regions(session, _ACCOUNT) == ("us-east-1",)


def test_analyze_policy_flags_admin_and_s3():
    # admin (*/*): also reads every bucket, no specific scoping.
    admin_doc = {"Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}
    assert _analyze_policy(admin_doc) == (True, True, set())

    # s3:* on Resource * → reads all buckets (wildcard), no specific names.
    s3_star = {"Statement": [{"Effect": "Allow", "Action": ["s3:*"], "Resource": "*"}]}
    assert _analyze_policy(s3_star) == (False, True, set())

    # scoped to a specific bucket → that bucket only, not all.
    scoped = {"Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::crown-jewels/*"}]}
    assert _analyze_policy(scoped) == (False, False, {"crown-jewels"})

    benign = {"Statement": [{"Effect": "Allow", "Action": ["ec2:DescribeInstances"], "Resource": "*"}]}
    assert _analyze_policy(benign) == (False, False, set())

    deny_star = {"Statement": [{"Effect": "Deny", "Action": "*", "Resource": "*"}]}
    assert _analyze_policy(deny_star) == (False, False, set())
