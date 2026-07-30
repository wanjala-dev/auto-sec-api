"""The boto3 inventory adapter builds the toxic-path graph the analyzer needs.

Fakes the AWS clients (no network, no creds) + the account-access port, runs the adapter
against the real asset store, then materializes attack paths — asserting a public EC2
instance whose instance-profile role carries AdministratorAccess yields a real
PUBLIC_COMPUTE_ADMIN path. Also unit-tests the policy-document analysis.
"""

from __future__ import annotations

import pytest

from components.cloud_graph.application.providers.cloud_graph_provider import CloudGraphProvider
from components.cloud_graph.domain.value_objects.enums import AssetRelation, Exposure
from components.cloud_graph.infrastructure.adapters.boto3_inventory_adapter import (
    Boto3InventoryAdapter,
    _analyze_policy,
    _policy_allows_public_principal,
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


class _FakeLambda:
    """Zero functions by default; pass functions + a URL auth / resource policy to make one public."""

    def __init__(self, functions=None, url_auth=None, resource_policy=None):
        self._functions = functions or []
        self._url_auth = url_auth  # e.g. "NONE" → public
        self._resource_policy = resource_policy  # dict → checked for a public principal

    def get_paginator(self, name):
        if name == "list_functions":
            return _Paginator([{"Functions": self._functions}])
        return _Paginator([])

    def get_function_url_config(self, FunctionName):
        if self._url_auth is None:
            raise RuntimeError("ResourceNotFoundException: no function url config")
        return {"AuthType": self._url_auth}

    def get_policy(self, FunctionName):
        if self._resource_policy is None:
            raise RuntimeError("ResourceNotFoundException: no resource policy")
        import json

        return {"Policy": json.dumps(self._resource_policy)}


class _FakeDynamoDb:
    def __init__(self, tables=None):
        self._tables = tables or []

    def get_paginator(self, name):
        if name == "list_tables":
            return _Paginator([{"TableNames": self._tables}])
        return _Paginator([])


class _FakeSession:
    def __init__(
        self,
        sg_open=True,
        regions=None,
        describe_regions_error=False,
        lambda_functions=None,
        lambda_url_auth=None,
        lambda_resource_policy=None,
        dynamodb_tables=None,
    ):
        self._sg_open = sg_open
        self._regions = regions
        self._describe_regions_error = describe_regions_error
        self._lambda_functions = lambda_functions
        self._lambda_url_auth = lambda_url_auth
        self._lambda_resource_policy = lambda_resource_policy
        self._dynamodb_tables = dynamodb_tables

    def client(self, name, region_name=None):
        return {
            "ec2": _FakeEc2(
                sg_open=self._sg_open,
                regions=self._regions,
                describe_regions_error=self._describe_regions_error,
            ),
            "iam": _FakeIam(),
            "s3": _FakeS3(),
            "lambda": _FakeLambda(
                functions=self._lambda_functions,
                url_auth=self._lambda_url_auth,
                resource_policy=self._lambda_resource_policy,
            ),
            "dynamodb": _FakeDynamoDb(tables=self._dynamodb_tables),
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


def test_collect_emits_public_lambda_and_dynamodb_with_edges():
    """The adapter emits a PUBLIC Lambda (URL AuthType NONE) linked to its execution role
    (ATTACHED_TO), a DynamoDB table node, and — since the role has admin (*/*) — a READS_TABLE
    edge to that table. This is the serverless-compute + NoSQL-data reach the analyzer walks."""
    import uuid

    from django.utils import timezone

    role_arn = f"arn:aws:iam::{_ACCOUNT}:role/app-role"
    session = _FakeSession(
        lambda_functions=[
            {
                "FunctionArn": f"arn:aws:lambda:us-east-1:{_ACCOUNT}:function:api",
                "FunctionName": "api",
                "Role": role_arn,
            }
        ],
        lambda_url_auth="NONE",
        dynamodb_tables=["Orders"],
    )
    adapter = Boto3InventoryAdapter(access_port=_FakeAccess(), regions=["us-east-1"])
    assets, edges = adapter._collect(uuid.uuid4(), _ACCOUNT, session, timezone.now())

    lambdas = [a for a in assets if a.resource_type == "AwsLambdaFunction"]
    assert len(lambdas) == 1 and lambdas[0].exposure is Exposure.PUBLIC
    tables = [a for a in assets if a.resource_type == "AwsDynamoDbTable"]
    assert len(tables) == 1 and tables[0].name == "Orders"

    lam_arn, table_arn = lambdas[0].arn, tables[0].arn
    assert any(
        e.src_arn == lam_arn and e.dst_arn == role_arn and e.relation is AssetRelation.ATTACHED_TO for e in edges
    )
    assert any(
        e.src_arn == role_arn and e.dst_arn == table_arn and e.relation is AssetRelation.READS_TABLE for e in edges
    )


@pytest.mark.django_db
def test_public_lambda_alone_yields_an_attack_path(workspace_factory):
    """With the EC2 made unreachable (closed SG), the ONLY public entry is the Lambda — so a
    path found proves the serverless path: public λ → execution role → admin policy / data."""
    workspace_id = workspace_factory().id
    store = CloudGraphProvider.build_cloud_asset_store()
    role_arn = f"arn:aws:iam::{_ACCOUNT}:role/app-role"
    adapter = Boto3InventoryAdapter(
        access_port=_FakeAccess(),
        asset_store=store,
        session_factory=lambda _creds: _FakeSession(
            sg_open=False,  # EC2 not internet-reachable → not an entry
            lambda_functions=[
                {
                    "FunctionArn": f"arn:aws:lambda:us-east-1:{_ACCOUNT}:function:api",
                    "FunctionName": "api",
                    "Role": role_arn,
                }
            ],
            lambda_url_auth="NONE",
            dynamodb_tables=["Orders"],
        ),
        regions=["us-east-1"],
    )
    adapter.sync_workspace(workspace_id)

    from django.utils import timezone

    paths = CloudGraphProvider.build_materialize_attack_paths_use_case().execute(workspace_id, timezone.now())
    assert paths.paths_found >= 1


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
    # admin (*/*): also reads every bucket AND every table, no specific scoping.
    admin = _analyze_policy({"Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]})
    assert admin.is_admin and admin.reads_all_s3 and admin.reads_all_dynamodb
    assert admin.s3_buckets == frozenset() and admin.dynamodb_tables == frozenset()

    # s3:* on Resource * → reads all buckets (wildcard), no specific names, no dynamo.
    s3_star = _analyze_policy({"Statement": [{"Effect": "Allow", "Action": ["s3:*"], "Resource": "*"}]})
    assert not s3_star.is_admin and s3_star.reads_all_s3 and not s3_star.reads_all_dynamodb

    # scoped to a specific bucket → that bucket only, not all.
    scoped = _analyze_policy(
        {"Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::crown-jewels/*"}]}
    )
    assert not scoped.reads_all_s3 and scoped.s3_buckets == frozenset({"crown-jewels"})

    benign = _analyze_policy({"Statement": [{"Effect": "Allow", "Action": ["ec2:DescribeInstances"], "Resource": "*"}]})
    assert not benign.is_admin and not benign.reads_all_s3 and not benign.reads_all_dynamodb

    deny_star = _analyze_policy({"Statement": [{"Effect": "Deny", "Action": "*", "Resource": "*"}]})
    assert not deny_star.is_admin and not deny_star.reads_all_s3 and not deny_star.reads_all_dynamodb


def test_analyze_policy_flags_dynamodb_reach():
    # dynamodb:* on Resource * → reads all tables.
    ddb_star = _analyze_policy({"Statement": [{"Effect": "Allow", "Action": ["dynamodb:*"], "Resource": "*"}]})
    assert ddb_star.reads_all_dynamodb and ddb_star.dynamodb_tables == frozenset()

    # scoped to a specific table (+ index subresource) → that table's root ARN only.
    scoped = _analyze_policy(
        {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": ["dynamodb:GetItem"],
                    "Resource": "arn:aws:dynamodb:us-east-1:111122223333:table/Orders/index/by-date",
                }
            ]
        }
    )
    assert not scoped.reads_all_dynamodb
    assert scoped.dynamodb_tables == frozenset({"arn:aws:dynamodb:us-east-1:111122223333:table/Orders"})


def test_policy_allows_public_principal():
    assert _policy_allows_public_principal({"Statement": [{"Effect": "Allow", "Principal": "*"}]})
    assert _policy_allows_public_principal({"Statement": [{"Effect": "Allow", "Principal": {"AWS": "*"}}]})
    assert not _policy_allows_public_principal(
        {"Statement": [{"Effect": "Allow", "Principal": {"AWS": "arn:aws:iam::111122223333:root"}}]}
    )
    assert not _policy_allows_public_principal({"Statement": [{"Effect": "Deny", "Principal": "*"}]})
