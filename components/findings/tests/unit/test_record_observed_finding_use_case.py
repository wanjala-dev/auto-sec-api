"""Unit tests for RecordObservedFindingUseCase — dedup, lifecycle, event emission.

Fake store + fake publisher; no DB, no framework.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from components.findings.application.commands.record_observed_finding_command import (
    RecordObservedFindingCommand,
)
from components.findings.application.ports.finding_store_port import FindingStorePort
from components.findings.application.use_cases.record_observed_finding_use_case import (
    RecordObservedFindingUseCase,
)
from components.findings.domain.entities.finding_entity import FindingEntity
from components.shared_kernel.domain.events import FindingRaised
from components.shared_kernel.domain.security import FindingStatus, Severity

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)
_WS = uuid4()


class _FakeStore(FindingStorePort):
    def __init__(self) -> None:
        self.by_identity: dict[tuple, FindingEntity] = {}

    def find_by_identity(self, workspace_id: UUID, source: str, fingerprint: str):
        return self.by_identity.get((workspace_id, source, fingerprint))

    def upsert(self, finding: FindingEntity) -> None:
        self.by_identity[(finding.workspace_id, finding.source, finding.fingerprint)] = finding


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list = []

    def publish(self, event) -> None:
        self.published.append(event)


def _cmd(**overrides) -> RecordObservedFindingCommand:
    base = dict(
        workspace_id=_WS,
        source="cloud_posture.prowler",
        fingerprint="fp-1",
        asset_urn="arn:aws:s3:::b",
        severity=Severity.HIGH,
        title="S3 public",
        observed_at=_NOW,
    )
    base.update(overrides)
    return RecordObservedFindingCommand(**base)


def _use_case():
    store = _FakeStore()
    publisher = _FakePublisher()
    return RecordObservedFindingUseCase(store=store, event_publisher=publisher), store, publisher


def test_first_observation_creates_open_and_raises_new():
    uc, store, pub = _use_case()
    result = uc.execute(_cmd())
    assert result.is_new is True and result.changed is True
    stored = store.by_identity[(_WS, "cloud_posture.prowler", "fp-1")]
    assert stored.status is FindingStatus.OPEN
    assert len(pub.published) == 1
    raised = pub.published[0]
    assert isinstance(raised, FindingRaised)
    assert raised.is_new is True
    assert raised.finding_id == result.finding_id
    assert raised.severity == "high"


def test_reobservation_unchanged_bumps_last_seen_without_raising():
    uc, store, pub = _use_case()
    uc.execute(_cmd())
    later = _NOW + timedelta(days=1)
    result = uc.execute(_cmd(observed_at=later))
    assert result.is_new is False and result.changed is False
    # No second event — steady-state noise is suppressed.
    assert len(pub.published) == 1
    stored = store.by_identity[(_WS, "cloud_posture.prowler", "fp-1")]
    assert stored.last_seen_at == later
    assert stored.first_seen_at == _NOW


def test_severity_change_raises_again():
    uc, store, pub = _use_case()
    uc.execute(_cmd())
    result = uc.execute(_cmd(severity=Severity.CRITICAL, observed_at=_NOW + timedelta(hours=1)))
    assert result.changed is True
    assert len(pub.published) == 2
    assert pub.published[1].is_new is False
    assert pub.published[1].severity == "critical"


def test_reobservation_after_resolution_reopens_and_raises():
    uc, store, pub = _use_case()
    first = uc.execute(_cmd())
    # Resolve it out of band.
    stored = store.by_identity[(_WS, "cloud_posture.prowler", "fp-1")]
    store.upsert(stored.resolved(at=_NOW + timedelta(hours=1)))
    # Re-observed → reopened.
    result = uc.execute(_cmd(observed_at=_NOW + timedelta(days=1)))
    assert result.changed is True
    assert result.finding_id == first.finding_id
    reopened = store.by_identity[(_WS, "cloud_posture.prowler", "fp-1")]
    assert reopened.status is FindingStatus.OPEN
    assert reopened.resolved_at is None
    assert len(pub.published) == 2
    assert pub.published[1].is_new is False


def test_publisher_optional_never_breaks_persistence():
    store = _FakeStore()
    uc = RecordObservedFindingUseCase(store=store, event_publisher=None)
    result = uc.execute(_cmd())
    assert result.is_new is True
    assert store.by_identity  # persisted despite no publisher
