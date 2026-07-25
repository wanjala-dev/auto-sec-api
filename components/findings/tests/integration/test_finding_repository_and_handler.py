"""Integration tests: the Django repository dedups + the handler persists an event.

The repository and the FindingObserved → persist path against a real DB. The handler
is exercised with a real repository but a fake publisher (isolating the persist path
from the event bus, which Phase 3b wires).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest

from components.findings.application.providers.finding_provider import FindingProvider
from components.findings.application.use_cases.record_observed_finding_use_case import (
    RecordObservedFindingUseCase,
)
from components.findings.domain.entities.finding_entity import FindingEntity
from components.findings.infrastructure.repositories.django_finding_repository import (
    DjangoFindingRepository,
)
from components.shared_kernel.domain.events import FindingObserved
from components.shared_kernel.domain.security import FindingStatus, Severity
from infrastructure.persistence.findings.models import Finding

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


class _FakePublisher:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


def _entity(ws, **overrides) -> FindingEntity:
    base = dict(
        id=uuid4(),
        workspace_id=ws.id,
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


def test_repository_upserts_and_dedups_on_identity(workspace_factory):
    ws = workspace_factory()
    repo = DjangoFindingRepository()

    repo.upsert(_entity(ws))
    # Same identity, later observation — must update, not duplicate.
    later = _NOW + timedelta(days=1)
    stored = repo.find_by_identity(ws.id, "cloud_posture.prowler", "fp-1")
    repo.upsert(
        stored.observed(
            at=later,
            severity=Severity.CRITICAL,
            title="worse",
            description="",
            remediation="",
            compliance={},
            attributes={},
        )
    )

    assert Finding.objects.filter(workspace=ws, source="cloud_posture.prowler", fingerprint="fp-1").count() == 1
    reloaded = repo.find_by_identity(ws.id, "cloud_posture.prowler", "fp-1")
    assert reloaded.severity is Severity.CRITICAL
    assert reloaded.last_seen_at == later
    assert reloaded.first_seen_at == _NOW


def test_find_by_identity_returns_none_when_absent(workspace_factory):
    ws = workspace_factory()
    assert DjangoFindingRepository().find_by_identity(ws.id, "x", "y") is None


def test_handler_persists_finding_observed_event(workspace_factory):
    ws = workspace_factory()
    from components.findings.application.handlers.finding_observed_handler import (
        handle_finding_observed,
    )

    event = FindingObserved(
        workspace_id=ws.id,
        source="cloud_posture.prowler",
        fingerprint="iam-root-mfa:acct-1",
        asset_urn="arn:aws:iam::1:root",
        severity=Severity.CRITICAL.value,
        title="Root account without MFA",
        description="The root user has no MFA device.",
        remediation="Enable MFA on the root account.",
        compliance={"CIS-2.0": ["1.5"]},
        attributes={"account_id": "1"},
    )

    fake = _FakePublisher()
    use_case = RecordObservedFindingUseCase(store=DjangoFindingRepository(), event_publisher=fake)
    with patch.object(FindingProvider, "build_record_observed_finding_use_case", return_value=use_case):
        handle_finding_observed(event)

    row = Finding.objects.get(workspace=ws, fingerprint="iam-root-mfa:acct-1")
    assert row.severity == "critical"
    assert row.status == "open"
    assert row.asset_urn == "arn:aws:iam::1:root"
    assert row.compliance == {"CIS-2.0": ["1.5"]}
    # The handler's use case emitted a FindingRaised for the new finding.
    assert len(fake.published) == 1
    assert fake.published[0].is_new is True
