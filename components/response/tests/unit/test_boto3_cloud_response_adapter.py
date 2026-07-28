"""Adapter unit tests — the boto3 DryRun / ClientError interpretation, no AWS."""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from components.response.domain.value_objects.response_action_kind import ResponseActionKind
from components.response.domain.value_objects.response_action_spec import ResponseActionSpec
from components.response.domain.value_objects.security_group_rule import SecurityGroupRule
from components.response.infrastructure.adapters.boto3_cloud_response_adapter import (
    Boto3CloudResponseAdapter,
)

pytestmark = pytest.mark.unit


class _FakeEc2:
    def __init__(self, *, revoke=None, revoke_error=None, rules=None):
        self._revoke = revoke or {"Return": True, "RevokedSecurityGroupRules": [{"SecurityGroupRuleId": "sgr-1"}]}
        self._revoke_error = revoke_error
        self._rules = rules or []
        self.calls = []

    def revoke_security_group_ingress(self, **kwargs):
        self.calls.append(("revoke", kwargs))
        if self._revoke_error is not None:
            raise self._revoke_error
        return {**self._revoke, "ResponseMetadata": {"HTTPStatusCode": 200}}

    def authorize_security_group_ingress(self, **kwargs):
        self.calls.append(("authorize", kwargs))
        return {"Return": True, "ResponseMetadata": {}}

    def describe_security_group_rules(self, **kwargs):
        self.calls.append(("describe", kwargs))
        return {"SecurityGroupRules": self._rules}


class _StubAdapter(Boto3CloudResponseAdapter):
    """Bypass creds + boto3 — hand the apply()/describe logic a fake EC2 client."""

    def __init__(self, fake):
        self._fake = fake

    def _ec2_client(self, *, workspace_id, account_id, region):
        return self._fake


def _spec(kind=ResponseActionKind.REVOKE_SG_INGRESS):
    return ResponseActionSpec(
        kind=kind,
        account_id="123456789012",
        region="us-east-1",
        group_id="sg-abc",
        rule=SecurityGroupRule(protocol="tcp", from_port=22, to_port=22, cidr="0.0.0.0/0"),
    )


def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "RevokeSecurityGroupIngress")


class TestApply:
    def test_real_revoke_marks_performed(self, settings):
        settings.SOC_RESPONSE_READ_ONLY = False  # a real execute requires opting out of the guard
        fake = _FakeEc2()
        outcome = _StubAdapter(fake).apply(_spec(), workspace_id="w", dry_run=False)
        assert outcome.performed and outcome.ok and not outcome.dry_run
        assert fake.calls[0][0] == "revoke"
        assert fake.calls[0][1]["DryRun"] is False

    def test_read_only_guard_downgrades_real_execute_to_dryrun(self, settings):
        # The read-only guarantee (default): a requested real execute is forced to a DryRun
        # probe at the AWS boundary — autosec never mutates the customer's cloud.
        settings.SOC_RESPONSE_READ_ONLY = True
        fake = _FakeEc2(revoke_error=_client_error("DryRunOperation"))
        outcome = _StubAdapter(fake).apply(_spec(), workspace_id="w", dry_run=False)
        assert fake.calls[0][1]["DryRun"] is True  # forced, despite dry_run=False
        assert outcome.dry_run and not outcome.performed

    def test_dry_run_permitted_would_succeed(self):
        fake = _FakeEc2(revoke_error=_client_error("DryRunOperation"))
        outcome = _StubAdapter(fake).apply(_spec(), workspace_id="w", dry_run=True)
        assert outcome.dry_run and outcome.would_succeed and not outcome.performed
        assert outcome.ok and outcome.error is None

    def test_dry_run_unauthorized_reports_error(self):
        fake = _FakeEc2(revoke_error=_client_error("UnauthorizedOperation"))
        outcome = _StubAdapter(fake).apply(_spec(), workspace_id="w", dry_run=True)
        assert outcome.dry_run and not outcome.would_succeed
        assert not outcome.ok and outcome.error is not None

    def test_other_client_error_surfaces(self):
        fake = _FakeEc2(revoke_error=_client_error("InvalidPermission.NotFound"))
        outcome = _StubAdapter(fake).apply(_spec(), workspace_id="w", dry_run=False)
        assert not outcome.ok and outcome.error is not None

    def test_authorize_routes_to_authorize_call(self):
        fake = _FakeEc2()
        _StubAdapter(fake).apply(_spec(ResponseActionKind.AUTHORIZE_SG_INGRESS), workspace_id="w", dry_run=False)
        assert fake.calls[0][0] == "authorize"


class TestFindMatchingPublicIngress:
    def test_matches_public_rule(self):
        fake = _FakeEc2(
            rules=[
                {"IsEgress": True, "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "CidrIpv4": "0.0.0.0/0"},
                {"IsEgress": False, "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "CidrIpv4": "10.0.0.0/8"},
                {"IsEgress": False, "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "CidrIpv4": "0.0.0.0/0"},
            ]
        )
        match = _StubAdapter(fake).find_matching_public_ingress(
            workspace_id="w",
            account_id="123456789012",
            region="us-east-1",
            group_id="sg-abc",
            rule=_spec().rule,
        )
        assert match is not None and match.is_public and not match.is_ipv6

    def test_no_match_when_only_scoped_or_egress(self):
        fake = _FakeEc2(
            rules=[
                {"IsEgress": True, "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "CidrIpv4": "0.0.0.0/0"},
                {"IsEgress": False, "IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "CidrIpv4": "10.0.0.0/8"},
            ]
        )
        match = _StubAdapter(fake).find_matching_public_ingress(
            workspace_id="w",
            account_id="123456789012",
            region="us-east-1",
            group_id="sg-abc",
            rule=_spec().rule,
        )
        assert match is None
