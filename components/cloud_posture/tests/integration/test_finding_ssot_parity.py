"""Dual-write parity: the Finding SSOT matches the CloudPostureFinding path (ADR 0004).

End-to-end through the REAL bus (Celery is eager in test settings, and the findings
handler is bound at app ready()): ``ingest_prowler_scan`` → ``FindingObserved`` on
commit → the findings handler persists a ``Finding``. This proves the production chain
works AND that the new SSOT is at parity before Phase 3c switches the board onto it —
plus it demonstrates the SSOT's cross-scan dedup, which the per-scan CloudPostureFinding
model does not do. A durable regression guard, not a one-off check.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
    ingest_prowler_scan,
)
from infrastructure.persistence.cloud_posture.models import CloudPostureFinding
from infrastructure.persistence.findings.models import Finding

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "prowler_ocsf_sample.json"


def _records():
    return json.loads(_FIXTURE.read_text())


def _fingerprint(cp: CloudPostureFinding) -> str:
    return f"{cp.check_id}|{cp.account_id}|{cp.resource_uid}"


def _expected_urn(cp: CloudPostureFinding) -> str:
    return cp.resource_uid if cp.resource_uid else f"urn:aws:account/{cp.account_id}"


def test_ssot_matches_cloud_posture_findings(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()

    with django_capture_on_commit_callbacks(execute=True):
        # No event_publisher → the real CeleryEventPublisher; eager Celery runs the
        # bound findings handler synchronously when the on_commit callbacks fire.
        scan = ingest_prowler_scan(workspace_id=ws.id, account_id="123456789012", records=_records())

    cp_findings = list(CloudPostureFinding.objects.filter(scan=scan))
    ssot = Finding.objects.filter(workspace=ws, source="cloud_posture.prowler")

    # One Finding per actionable CloudPostureFinding (the fixture's PASS check is excluded).
    assert ssot.count() == len(cp_findings) == 2

    for cp in cp_findings:
        finding = ssot.get(fingerprint=_fingerprint(cp))
        assert finding.severity == cp.severity, f"severity drift for {cp.check_id}"
        assert finding.title == cp.title
        assert finding.status == "open"
        assert finding.compliance == cp.compliance
        assert finding.asset_urn == _expected_urn(cp)
        assert finding.description == cp.description
        assert finding.remediation == cp.remediation


def test_ssot_dedups_across_scans_where_cloud_posture_does_not(workspace_factory, django_capture_on_commit_callbacks):
    ws = workspace_factory()

    for _ in range(2):
        with django_capture_on_commit_callbacks(execute=True):
            ingest_prowler_scan(workspace_id=ws.id, account_id="123456789012", records=_records())

    # CloudPostureFinding is per-scan: two scans × two actionable checks = four rows.
    assert CloudPostureFinding.objects.filter(workspace=ws).count() == 4
    # The SSOT dedups on (workspace, source, fingerprint): still two findings, last_seen
    # bumped by the second observation. This is the cross-scan dedup the old model lacks.
    ssot = Finding.objects.filter(workspace=ws, source="cloud_posture.prowler")
    assert ssot.count() == 2
    for finding in ssot:
        assert finding.last_seen_at >= finding.first_seen_at
