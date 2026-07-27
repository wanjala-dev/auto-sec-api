"""End-to-end lifecycle over the real repository + a fake cloud port.

Proves the reversible flow through the persistence layer: propose (grounded) →
approve (executes) → rollback (runs the inverse), plus the guards (justification
required, illegal transitions rejected). The cloud port is faked — we assert the
*orchestration + ledger*, not boto3 (that is covered in the adapter unit test).
"""

from __future__ import annotations

import pytest

from components.response.application.ports.cloud_response_port import CloudResponsePort
from components.response.application.providers.response_provider import build_response_service
from components.response.domain.errors import IllegalTransitionError, ResponseActionError
from components.response.domain.value_objects.execution_status import ExecutionStatus
from components.response.domain.value_objects.response_action_kind import ResponseActionKind
from components.response.domain.value_objects.response_action_spec import ResponseActionSpec
from components.response.domain.value_objects.response_outcome import ResponseOutcome
from components.response.domain.value_objects.security_group_rule import SecurityGroupRule
from components.response.infrastructure.repositories.response_action_repository import (
    DjangoResponseActionRepository,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


class FakeCloudPort(CloudResponsePort):
    def __init__(self, *, match=True):
        self._match = match
        self.applied = []

    def apply(self, spec, *, workspace_id, dry_run):
        self.applied.append((spec.kind, dry_run))
        return ResponseOutcome(performed=not dry_run, dry_run=dry_run, would_succeed=True, detail={"Return": True})

    def find_matching_public_ingress(self, *, workspace_id, account_id, region, group_id, rule):
        return rule if self._match else None


def _spec():
    return ResponseActionSpec(
        kind=ResponseActionKind.REVOKE_SG_INGRESS,
        account_id="123456789012",
        region="us-east-1",
        group_id="sg-abc",
        rule=SecurityGroupRule(protocol="tcp", from_port=22, to_port=22, cidr="0.0.0.0/0"),
    )


def _service(match=True, cloud=None):
    cloud = cloud or FakeCloudPort(match=match)
    return build_response_service(store=DjangoResponseActionRepository(), cloud_port=cloud), cloud


def _propose(service, workspace, dry_run=True):
    return service.propose(
        workspace_id=workspace.id,
        finding_fingerprint="fp-attack-path-1",
        spec=_spec(),
        requested_by="agent",
        dry_run=dry_run,
    )


class TestReversibleFlow:
    def test_propose_persists_pending_with_inverse(self, workspace_factory):
        ws = workspace_factory()
        service, _ = _service()
        action = _propose(service, ws)
        assert action.status == ExecutionStatus.PROPOSED
        assert action.inverse_spec.kind == ResponseActionKind.AUTHORIZE_SG_INGRESS
        # round-trips through the DB
        reloaded = service.get(action_id=action.id, workspace_id=ws.id)
        assert reloaded is not None and reloaded.status == ExecutionStatus.PROPOSED

    def test_propose_rejects_ungrounded_target(self, workspace_factory):
        ws = workspace_factory()
        service, _ = _service(match=False)
        from components.response.domain.errors import UnsafeActionError

        with pytest.raises(UnsafeActionError):
            _propose(service, ws)

    def test_approve_executes_and_rollback_runs_inverse(self, workspace_factory):
        ws = workspace_factory()
        service, cloud = _service()
        action = _propose(service, ws, dry_run=False)

        approved = service.approve(
            action_id=action.id, workspace_id=ws.id, approver_id="operator-1", justification="close public SSH"
        )
        assert approved.status == ExecutionStatus.EXECUTED
        assert approved.executed_at is not None
        assert (ResponseActionKind.REVOKE_SG_INGRESS, False) in cloud.applied

        rolled = service.rollback(action_id=action.id, workspace_id=ws.id, actor_id="operator-1")
        assert rolled.status == ExecutionStatus.ROLLED_BACK
        assert (ResponseActionKind.AUTHORIZE_SG_INGRESS, False) in cloud.applied

    def test_approve_requires_justification(self, workspace_factory):
        ws = workspace_factory()
        service, _ = _service()
        action = _propose(service, ws)
        with pytest.raises(ResponseActionError):
            service.approve(action_id=action.id, workspace_id=ws.id, approver_id="op", justification="  ")

    def test_reject_blocks_execution(self, workspace_factory):
        ws = workspace_factory()
        service, cloud = _service()
        action = _propose(service, ws)
        rejected = service.reject(action_id=action.id, workspace_id=ws.id, actor_id="op", note="false positive")
        assert rejected.status == ExecutionStatus.REJECTED
        with pytest.raises(IllegalTransitionError):
            service.approve(action_id=action.id, workspace_id=ws.id, approver_id="op", justification="x")
        assert cloud.applied == []

    def test_cannot_rollback_before_execute(self, workspace_factory):
        ws = workspace_factory()
        service, _ = _service()
        action = _propose(service, ws)
        with pytest.raises(IllegalTransitionError):
            service.rollback(action_id=action.id, workspace_id=ws.id, actor_id="op")

    def test_dry_run_approve_does_not_perform(self, workspace_factory):
        ws = workspace_factory()
        service, cloud = _service()
        action = _propose(service, ws, dry_run=True)
        approved = service.approve(
            action_id=action.id, workspace_id=ws.id, approver_id="op", justification="probe only"
        )
        assert approved.status == ExecutionStatus.EXECUTED  # dry-run "executed" = permission-proven
        assert (ResponseActionKind.REVOKE_SG_INGRESS, True) in cloud.applied

    def test_workspace_isolation(self, workspace_factory):
        ws_a = workspace_factory()
        ws_b = workspace_factory()
        service, _ = _service()
        action = _propose(service, ws_a)
        assert service.get(action_id=action.id, workspace_id=ws_b.id) is None
