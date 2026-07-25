"""Round-trip tests for the CNAPP finding-spine events (ADR 0004 Phase 1).

These events cross the Celery wire via ``CeleryEventPublisher``, so the load-bearing
guarantee is that every field survives ``_serialise_event`` → ``_deserialise_event``
unchanged. If a future field uses a type the encoder does not handle (an Enum, a
value object), it silently drops the event in prod — this suite makes that a red
test instead. Mirrors ``test_celery_event_publisher_serialisation.py``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from components.shared_kernel.domain.events import (
    AttackPathDetected,
    FindingObserved,
    FindingRaised,
    FindingResolved,
)
from components.shared_kernel.domain.security import FindingStatus, Severity
from components.shared_kernel.infrastructure.adapters.celery_event_publisher import (
    _deserialise_event,
    _serialise_event,
)


def _fqn(klass: type) -> str:
    return f"{klass.__module__}.{klass.__name__}"


@pytest.mark.unit
class TestFindingEventsRoundTrip:
    def test_finding_observed_round_trips(self):
        ws = uuid4()
        event = FindingObserved(
            workspace_id=ws,
            source="cloud_posture.prowler",
            fingerprint="s3-public-acl:arn:aws:s3:::b",
            asset_urn="arn:aws:s3:::b",
            severity=Severity.HIGH.value,
            title="S3 bucket allows public ACL",
            description="Bucket b grants READ to AllUsers.",
            remediation="Remove the public ACL grant.",
            compliance={"CIS-2.0": ["2.1.5"]},
            attributes={"region": "us-east-1", "account_id": "123"},
        )
        data = _serialise_event(event)
        rebuilt = _deserialise_event(_fqn(FindingObserved), data)

        assert isinstance(rebuilt, FindingObserved)
        assert rebuilt.workspace_id == ws
        assert rebuilt.source == "cloud_posture.prowler"
        assert rebuilt.severity == "high"
        assert Severity.from_name(rebuilt.severity) is Severity.HIGH
        assert rebuilt.compliance == {"CIS-2.0": ["2.1.5"]}
        assert rebuilt.attributes["region"] == "us-east-1"

    def test_finding_observed_defaults(self):
        event = FindingObserved(
            workspace_id=uuid4(),
            source="cloud_posture.prowler",
            fingerprint="fp",
            asset_urn="arn:aws:s3:::b",
            severity=Severity.LOW.value,
            title="t",
        )
        rebuilt = _deserialise_event(_fqn(FindingObserved), _serialise_event(event))
        assert rebuilt.description == ""
        assert rebuilt.remediation == ""
        assert rebuilt.compliance == {}
        assert rebuilt.attributes == {}

    def test_finding_raised_round_trips(self):
        ws, fid = uuid4(), uuid4()
        event = FindingRaised(
            workspace_id=ws,
            finding_id=fid,
            fingerprint="fp",
            asset_urn="arn:aws:s3:::b",
            severity=Severity.CRITICAL.value,
            status=FindingStatus.OPEN.value,
            source="cloud_posture.prowler",
            title="t",
            is_new=True,
        )
        rebuilt = _deserialise_event(_fqn(FindingRaised), _serialise_event(event))
        assert rebuilt.workspace_id == ws
        assert rebuilt.finding_id == fid
        assert rebuilt.is_new is True
        assert FindingStatus(rebuilt.status) is FindingStatus.OPEN
        assert Severity.from_name(rebuilt.severity) is Severity.CRITICAL

    def test_finding_resolved_round_trips(self):
        ws, fid = uuid4(), uuid4()
        event = FindingResolved(
            workspace_id=ws,
            finding_id=fid,
            fingerprint="fp",
            reason="no_longer_observed",
        )
        rebuilt = _deserialise_event(_fqn(FindingResolved), _serialise_event(event))
        assert rebuilt.finding_id == fid
        assert rebuilt.reason == "no_longer_observed"

    def test_attack_path_detected_round_trips(self):
        ws, pid = uuid4(), uuid4()
        f1, f2 = str(uuid4()), str(uuid4())
        event = AttackPathDetected(
            workspace_id=ws,
            path_id=pid,
            severity=Severity.CRITICAL.value,
            title="Public bucket reachable by over-permissioned role",
            asset_urns=["arn:aws:iam::123:role/admin", "arn:aws:s3:::b"],
            finding_ids=[f1, f2],
        )
        rebuilt = _deserialise_event(_fqn(AttackPathDetected), _serialise_event(event))
        assert rebuilt.path_id == pid
        assert rebuilt.asset_urns == ["arn:aws:iam::123:role/admin", "arn:aws:s3:::b"]
        assert rebuilt.finding_ids == [f1, f2]

    def test_base_domain_event_fields_survive(self):
        # event_id + occurred_at come from DomainEvent and must round-trip too.
        event = FindingResolved(
            workspace_id=uuid4(),
            finding_id=uuid4(),
            fingerprint="fp",
        )
        rebuilt = _deserialise_event(_fqn(FindingResolved), _serialise_event(event))
        assert rebuilt.event_id == event.event_id
        assert rebuilt.occurred_at == event.occurred_at
