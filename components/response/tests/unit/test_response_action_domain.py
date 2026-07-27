"""Pure-domain tests — no DB, no framework. The reversibility invariants."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from components.response.domain.entities.response_action_entity import ResponseActionExecution
from components.response.domain.errors import IllegalTransitionError
from components.response.domain.value_objects.execution_status import ExecutionStatus
from components.response.domain.value_objects.response_action_kind import ResponseActionKind
from components.response.domain.value_objects.response_action_spec import ResponseActionSpec
from components.response.domain.value_objects.security_group_rule import SecurityGroupRule

pytestmark = pytest.mark.unit


def _rule(cidr="0.0.0.0/0", protocol="tcp", from_port=22, to_port=22):
    return SecurityGroupRule(protocol=protocol, from_port=from_port, to_port=to_port, cidr=cidr)


def _spec(kind=ResponseActionKind.REVOKE_SG_INGRESS, rule=None):
    return ResponseActionSpec(
        kind=kind,
        account_id="123456789012",
        region="us-east-1",
        group_id="sg-abc123",
        rule=rule or _rule(),
    )


class TestSecurityGroupRule:
    def test_ipv4_ip_permissions_shape(self):
        perms = _rule().to_ip_permissions()
        assert perms == [{"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]

    def test_ipv6_uses_ipv6_ranges(self):
        perms = _rule(cidr="::/0").to_ip_permissions()
        assert "Ipv6Ranges" in perms[0]
        assert perms[0]["Ipv6Ranges"] == [{"CidrIpv6": "::/0"}]

    def test_all_protocol_omits_ports(self):
        rule = SecurityGroupRule(protocol="-1", from_port=None, to_port=None, cidr="0.0.0.0/0")
        perms = rule.to_ip_permissions()
        assert "FromPort" not in perms[0] and "ToPort" not in perms[0]

    def test_public_detection(self):
        assert _rule(cidr="0.0.0.0/0").is_public
        assert _rule(cidr="::/0").is_public
        assert not _rule(cidr="10.0.0.0/8").is_public

    def test_half_specified_port_range_rejected(self):
        with pytest.raises(ValueError):
            SecurityGroupRule(protocol="tcp", from_port=22, to_port=None, cidr="0.0.0.0/0")


class TestResponseActionSpecInverse:
    def test_inverse_flips_verb_keeps_target(self):
        spec = _spec()
        inv = spec.inverse()
        assert inv.kind == ResponseActionKind.AUTHORIZE_SG_INGRESS
        assert (inv.account_id, inv.region, inv.group_id, inv.rule) == (
            spec.account_id,
            spec.region,
            spec.group_id,
            spec.rule,
        )

    def test_inverse_is_involutive(self):
        spec = _spec()
        assert spec.inverse().inverse() == spec

    def test_round_trips_through_dict(self):
        spec = _spec()
        assert ResponseActionSpec.from_dict(spec.to_dict()) == spec


class TestExecutionStatusTransitions:
    def test_only_proposed_can_be_decided(self):
        assert ExecutionStatus.PROPOSED.can_approve
        assert ExecutionStatus.PROPOSED.can_reject
        assert not ExecutionStatus.EXECUTED.can_approve
        assert not ExecutionStatus.EXECUTED.can_reject

    def test_only_executed_can_rollback(self):
        assert ExecutionStatus.EXECUTED.can_rollback
        assert not ExecutionStatus.PROPOSED.can_rollback
        assert not ExecutionStatus.ROLLED_BACK.can_rollback


class TestEntityLifecycle:
    def _proposed(self):
        spec = _spec()
        return ResponseActionExecution(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            finding_fingerprint="fp-1",
            spec=spec,
            inverse_spec=spec.inverse(),
            status=ExecutionStatus.PROPOSED,
            dry_run=True,
            requested_by="agent",
            requested_at=datetime.now(UTC),
        )

    def test_approve_then_rollback_path(self):
        now = datetime.now(UTC)
        approved = self._proposed().approved(decided_by="u1", decided_at=now, justification="closing exposure")
        assert approved.status == ExecutionStatus.EXECUTED
        executed = approved.with_execution_result(executed_at=now, detail={"Return": True}, failed=False, error=None)
        rolled = executed.rolled_back(rolled_back_at=now, detail={"Return": True})
        assert rolled.status == ExecutionStatus.ROLLED_BACK

    def test_cannot_rollback_a_proposal(self):
        with pytest.raises(IllegalTransitionError):
            self._proposed().rolled_back(rolled_back_at=datetime.now(UTC), detail={})

    def test_failed_execution_marks_failed(self):
        now = datetime.now(UTC)
        approved = self._proposed().approved(decided_by="u1", decided_at=now, justification="x")
        failed = approved.with_execution_result(executed_at=now, detail={"code": "X"}, failed=True, error="boom")
        assert failed.status == ExecutionStatus.FAILED
        assert failed.error == "boom"
