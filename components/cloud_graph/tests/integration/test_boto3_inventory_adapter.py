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
    def get_paginator(self, _name):
        return _Paginator(
            [
                {
                    "Reservations": [
                        {
                            "Instances": [
                                {
                                    "InstanceId": "i-0abc",
                                    "PublicIpAddress": "203.0.113.7",
                                    "IamInstanceProfile": {"Arn": f"arn:aws:iam::{_ACCOUNT}:instance-profile/app"},
                                    "Tags": [{"Key": "Name", "Value": "web"}],
                                }
                            ]
                        }
                    ]
                }
            ]
        )


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
    def client(self, name, region_name=None):
        return {"ec2": _FakeEc2(), "iam": _FakeIam(), "s3": _FakeS3()}[name]


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

    # instance + instance-profile + role + admin policy + bucket
    assert result.assets_upserted >= 5
    # ATTACHED_TO (instance→profile), CAN_ASSUME (profile→role), HAS_POLICY (role→policy), READS_BUCKET
    assert result.edges_upserted >= 4

    # The analyzer walks the graph: public web instance → profile → role → AdministratorAccess.
    from django.utils import timezone

    paths = CloudGraphProvider.build_materialize_attack_paths_use_case().execute(workspace_id, timezone.now())
    assert paths.paths_found >= 1


def test_analyze_policy_flags_admin_and_s3():
    admin_doc = {"Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}]}
    assert _analyze_policy(admin_doc) == (True, True)

    s3_only = {"Statement": [{"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": "arn:aws:s3:::x/*"}]}
    assert _analyze_policy(s3_only) == (False, True)

    benign = {"Statement": [{"Effect": "Allow", "Action": ["ec2:DescribeInstances"], "Resource": "*"}]}
    assert _analyze_policy(benign) == (False, False)

    deny_star = {"Statement": [{"Effect": "Deny", "Action": "*", "Resource": "*"}]}
    assert _analyze_policy(deny_star) == (False, False)
