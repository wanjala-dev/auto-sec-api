"""cloud_posture dual-writes actionable findings as FindingObserved events (Phase 3b).

The existing CloudPostureFinding path is unchanged; these tests cover the added
shared-kernel emit that fills the findings SSOT.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from components.cloud_posture.domain.entities.posture_finding_entity import NormalizedPostureFinding
from components.cloud_posture.domain.value_objects.enums import CheckStatus, Severity
from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
    _to_normalized,
    ingest_prowler_scan,
)
from components.shared_kernel.domain.events import FindingObserved, ScanCompleted

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
def test_to_normalized_maps_resource_finding():
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
    nf = _to_normalized(finding)
    assert nf.source == "cloud_posture.prowler"
    assert nf.fingerprint == "s3_bucket_public_access|123456789012|arn:aws:s3:::b"
    assert nf.asset_urn == "arn:aws:s3:::b"
    assert nf.severity.value == "high"
    assert nf.attributes["region"] == "us-east-1"
    assert nf.attributes["check_status"] == "fail"
    assert nf.compliance == {"CIS-2.0": ["2.1.5"]}


@pytest.mark.unit
def test_to_normalized_account_level_fallback():
    finding = NormalizedPostureFinding(
        check_id="iam_root_mfa_enabled",
        title="",  # account-level check, no resource / title
        severity=Severity.CRITICAL,
        status=CheckStatus.FAIL,
        account_id="123456789012",
        resource_uid="",
    )
    nf = _to_normalized(finding)
    # No resource → per-account URN so the required identity is never empty.
    assert nf.asset_urn == "urn:aws:account/123456789012"
    assert nf.title == "iam_root_mfa_enabled"  # falls back to check_id
    assert nf.severity.value == "critical"


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
    observed = [e for e in cap.published if isinstance(e, FindingObserved)]
    assert len(observed) == 2
    assert {e.source for e in observed} == {"cloud_posture.prowler"}
    checks = {e.attributes["check_id"] for e in observed}
    assert checks == {"s3_bucket_public_access", "iam_root_mfa_enabled"}


@pytest.mark.integration
@pytest.mark.django_db
def test_ingest_emits_exactly_one_scan_completed_digest(workspace_factory, django_capture_on_commit_callbacks):
    """The anti-flood digest signal (ADR 0016 D5): ONE ScanCompleted per ingest,
    carrying the severity counts the external digest renders."""
    ws = workspace_factory()
    cap = _CapturingPublisher()

    with django_capture_on_commit_callbacks(execute=True):
        scan = ingest_prowler_scan(
            workspace_id=ws.id,
            account_id="123456789012",
            records=_records(),
            event_publisher=cap,
        )

    completed = [e for e in cap.published if isinstance(e, ScanCompleted)]
    assert len(completed) == 1
    digest = completed[0]
    assert digest.workspace_id == ws.id
    assert digest.source == "cloud_posture.prowler"
    assert digest.engine == "prowler"
    assert digest.scan_id == str(scan.id)
    assert digest.account_id == "123456789012"
    assert digest.findings_observed == 2
    assert digest.critical + digest.high + digest.medium + digest.low == 2


@pytest.mark.integration
@pytest.mark.django_db
def test_ingest_does_not_emit_before_commit(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()
    cap = _CapturingPublisher()

    with django_capture_on_commit_callbacks(execute=False):
        ingest_prowler_scan(workspace_id=ws.id, account_id="1", records=_records(), event_publisher=cap)
        # on_commit deferred — nothing emitted yet inside the block.
        assert cap.published == []
