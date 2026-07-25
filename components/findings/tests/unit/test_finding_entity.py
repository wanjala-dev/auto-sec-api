"""Unit tests for FindingEntity invariants + lifecycle (no DB, no framework)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from components.findings.domain.entities.finding_entity import FindingEntity
from components.shared_kernel.domain.security import FindingStatus, Severity

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


def _finding(**overrides) -> FindingEntity:
    base = dict(
        id=uuid4(),
        workspace_id=uuid4(),
        source="cloud_posture.prowler",
        fingerprint="fp-1",
        asset_urn="arn:aws:s3:::b",
        severity=Severity.HIGH,
        status=FindingStatus.OPEN,
        title="S3 public",
        first_seen_at=_NOW,
        last_seen_at=_NOW,
    )
    base.update(overrides)
    return FindingEntity(**base)


def test_requires_identity_and_title():
    for missing in ("source", "fingerprint", "asset_urn", "title"):
        with pytest.raises(ValueError):
            _finding(**{missing: ""})


def test_is_open_reflects_status():
    assert _finding(status=FindingStatus.OPEN).is_open
    assert _finding(status=FindingStatus.TRIAGED).is_open
    assert not _finding(status=FindingStatus.RESOLVED).is_open
    assert not _finding(status=FindingStatus.SUPPRESSED).is_open


def test_observed_bumps_last_seen_and_preserves_first_seen():
    f = _finding()
    later = _NOW + timedelta(days=1)
    updated = f.observed(
        at=later,
        severity=Severity.CRITICAL,
        title="S3 public (worse)",
        description="d",
        remediation="r",
        compliance={"CIS": ["1"]},
        attributes={"a": 1},
    )
    assert updated.last_seen_at == later
    assert updated.first_seen_at == _NOW
    assert updated.severity is Severity.CRITICAL
    assert updated.title == "S3 public (worse)"


def test_observed_reopens_a_terminal_finding():
    resolved = _finding(status=FindingStatus.RESOLVED, resolved_at=_NOW)
    reopened = resolved.observed(
        at=_NOW + timedelta(days=1),
        severity=Severity.HIGH,
        title="t",
        description="",
        remediation="",
        compliance={},
        attributes={},
    )
    assert reopened.status is FindingStatus.OPEN
    assert reopened.resolved_at is None


def test_observed_keeps_triaged_status():
    triaged = _finding(status=FindingStatus.TRIAGED)
    updated = triaged.observed(
        at=_NOW,
        severity=Severity.HIGH,
        title="t",
        description="",
        remediation="",
        compliance={},
        attributes={},
    )
    assert updated.status is FindingStatus.TRIAGED


def test_resolved_sets_terminal_state():
    resolved = _finding().resolved(at=_NOW)
    assert resolved.status is FindingStatus.RESOLVED
    assert resolved.resolved_at == _NOW
    assert not resolved.is_open
