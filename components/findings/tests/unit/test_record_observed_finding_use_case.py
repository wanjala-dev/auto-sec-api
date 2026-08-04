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

    def find_by_id(self, workspace_id: UUID, finding_id: UUID):
        return next(
            (f for f in self.by_identity.values() if f.workspace_id == workspace_id and f.id == finding_id),
            None,
        )

    def upsert(self, finding: FindingEntity) -> None:
        self.by_identity[(finding.workspace_id, finding.source, finding.fingerprint)] = finding

    # Read side — unused by these write-path tests, but the port requires them.
    def list_findings(
        self, workspace_id, *, severity=None, status=None, source=None, asset_urn=None, limit=25, offset=0
    ):
        return []

    def list_ranked_findings(
        self,
        workspace_id,
        *,
        severity=None,
        status=None,
        source=None,
        asset_urn=None,
        order_by="contextual_risk",
        limit=25,
        offset=0,
    ):
        return []

    def get_ranked_finding(self, workspace_id, finding_id):
        return None

    def iter_scorable_findings(self, workspace_id, *, finding_id=None):
        return iter(())

    def list_workspace_ids_with_findings(self):
        return []

    def count_findings(self, workspace_id, *, severity=None, status=None, source=None, asset_urn=None):
        return 0

    def open_finding_asset_urns(self, workspace_id, *, severities=None):
        return []

    def open_finding_compliance(self, workspace_id):
        return []

    def has_real_findings(self, workspace_id, *, sample_prefix):
        return False

    def delete_sample_findings(self, workspace_id, *, sample_prefix):
        return 0


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


def test_raised_event_carries_vulnerability_identity_from_attributes():
    """SCA attributes (Trivy: vulnerability_id + pkg_name) ride onto FindingRaised so
    outbound alerts can disambiguate lookalike titles without a cross-context read."""
    uc, _store, pub = _use_case()
    uc.execute(_cmd(attributes={"vulnerability_id": "CVE-2025-12345", "pkg_name": "openssl"}))
    raised = pub.published[0]
    assert raised.vulnerability_id == "CVE-2025-12345"
    assert raised.package == "openssl"


def test_raised_event_vulnerability_fields_default_empty():
    """A CSPM finding with no vulnerability identity emits empty strings (additive field)."""
    uc, _store, pub = _use_case()
    uc.execute(_cmd())
    raised = pub.published[0]
    assert raised.vulnerability_id == ""
    assert raised.package == ""


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
