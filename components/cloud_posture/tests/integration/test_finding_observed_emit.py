"""cloud_posture dual-writes actionable findings as FindingObserved events (Phase 3b).

The existing CloudPostureFinding path is unchanged; these tests cover the added
shared-kernel emit that fills the findings SSOT.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from components.cloud_posture.domain.entities.posture_finding_entity import NormalizedPostureFinding
from components.cloud_posture.domain.value_objects.enums import CheckStatus, Severity
from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
    _build_finding_observed,
    ingest_prowler_scan,
)
from components.shared_kernel.domain.events import FindingObserved

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "prowler_ocsf_sample.json"
_NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


def _records():
    return json.loads(_FIXTURE.read_text())


class _CapturingPublisher:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)


@pytest.mark.unit
def test_build_finding_observed_maps_resource_finding():
    ws = uuid4()
    finding = NormalizedPostureFinding(
        check_id="s3_bucket_public_access",
        title="S3 public",
        severity=Severity.HIGH,
        status=CheckStatus.FAIL,
        account_id="123456789012",
        resource_uid="arn:aws:s3:::b",
        region="us-east-1",
        service="s3",
        compliance={"CIS-2.0": ["2.1.5"]},
    )
    event = _build_finding_observed(ws, finding, occurred_at=_NOW)
    assert isinstance(event, FindingObserved)
    assert event.workspace_id == ws
    assert event.source == "cloud_posture.prowler"
    assert event.fingerprint == "s3_bucket_public_access|123456789012|arn:aws:s3:::b"
    assert event.asset_urn == "arn:aws:s3:::b"
    assert event.severity == "high"
    assert event.attributes["region"] == "us-east-1"
    assert event.compliance == {"CIS-2.0": ["2.1.5"]}


@pytest.mark.unit
def test_build_finding_observed_account_level_fallback():
    finding = NormalizedPostureFinding(
        check_id="iam_root_mfa_enabled",
        title="",  # account-level check, no resource / title
        severity=Severity.CRITICAL,
        status=CheckStatus.FAIL,
        account_id="123456789012",
        resource_uid="",
    )
    event = _build_finding_observed(uuid4(), finding, occurred_at=_NOW)
    # No resource → per-account URN so the required identity is never empty.
    assert event.asset_urn == "urn:aws:account/123456789012"
    assert event.title == "iam_root_mfa_enabled"  # falls back to check_id
    assert event.severity == "critical"


@pytest.mark.integration
@pytest.mark.django_db
def test_ingest_emits_finding_observed_only_for_actionable(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()
    cap = _CapturingPublisher()

    with django_capture_on_commit_callbacks(execute=True):
        ingest_prowler_scan(
            workspace_id=ws.id,
            account_id="123456789012",
            records=_records(),
            event_publisher=cap,
        )

    # The fixture has 3 checks (2 actionable FAIL + 1 PASS) — only the 2 actionable
    # ones emit; the PASS is not surfaced.
    assert len(cap.published) == 2
    assert all(isinstance(e, FindingObserved) for e in cap.published)
    assert {e.source for e in cap.published} == {"cloud_posture.prowler"}
    checks = {e.attributes["check_id"] for e in cap.published}
    assert checks == {"s3_bucket_public_access", "iam_root_mfa_enabled"}


@pytest.mark.integration
@pytest.mark.django_db
def test_ingest_does_not_emit_before_commit(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()
    cap = _CapturingPublisher()

    with django_capture_on_commit_callbacks(execute=False):
        ingest_prowler_scan(workspace_id=ws.id, account_id="1", records=_records(), event_publisher=cap)
        # on_commit deferred — nothing emitted yet inside the block.
        assert cap.published == []
