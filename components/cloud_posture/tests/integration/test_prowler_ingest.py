"""Tests for the Prowler OCSF parser + cloud-posture ingest.

Fixture-driven — no live AWS. The parser tests are pure (no DB); the ingest
tests exercise persistence + within-scan dedup.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from components.cloud_posture.domain.value_objects.enums import CheckStatus, Severity
from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
    parse_prowler_ocsf,
)

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "prowler_ocsf_sample.json"


def _records():
    return json.loads(_FIXTURE.read_text())


@pytest.mark.unit
def test_parser_maps_ocsf_fields():
    parsed = parse_prowler_ocsf(_records())
    by_check = {p.check_id: p for p in parsed}

    assert len(parsed) == 3
    root = by_check["iam_root_mfa_enabled"]
    assert root.severity is Severity.CRITICAL
    assert root.status is CheckStatus.FAIL
    assert root.resource_uid == "arn:aws:iam::123456789012:root"
    assert root.account_id == "123456789012"

    s3 = by_check["s3_bucket_public_access"]
    assert s3.severity is Severity.HIGH
    assert s3.service == "s3"
    assert s3.region == "us-east-1"
    assert s3.compliance == {"CIS-2.0": ["2.1.5"]}
    assert "Block public access" in s3.remediation

    assert by_check["ec2_ebs_default_encryption"].status is CheckStatus.PASS


@pytest.mark.unit
def test_parser_skips_records_without_check_id():
    parsed = parse_prowler_ocsf([{"severity": "High", "status_code": "FAIL"}, {"not": "a dict"}])
    assert parsed == []


class _StubScanner:
    def __init__(self, result):
        self._result = result

    def scan(self, target, on_progress=None):
        return self._result


def _spine_ingest(ws, records):
    from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
        records_to_scan_result,
    )
    from components.scanning.infrastructure.services.run_scan_service import run_scan_and_ingest
    from components.shared_kernel.application.ports.scanner_port import ScanTarget

    return run_scan_and_ingest(
        workspace_id=ws.id,
        source="cloud_posture.prowler",
        target=ScanTarget(identifier="123456789012"),
        scanner=_StubScanner(records_to_scan_result(records, engine_version="prowler")),
        account_id="123456789012",
    )


@pytest.mark.integration
@pytest.mark.django_db
def test_spine_ingest_persists_run_and_actionable_findings(workspace_factory, django_capture_on_commit_callbacks):
    from infrastructure.persistence.findings.models import Finding

    ws = workspace_factory()
    with django_capture_on_commit_callbacks(execute=True):
        run = _spine_ingest(ws, _records())

    assert run.total_checks == 3
    assert run.passed_count == 1
    assert run.failed_count == 2

    findings = Finding.objects.filter(workspace=ws, source="cloud_posture.prowler")
    # Only the two non-PASS checks reach the SSOT.
    assert findings.count() == 2
    assert {f.attributes["check_id"] for f in findings} == {
        "s3_bucket_public_access",
        "iam_root_mfa_enabled",
    }
    crit = findings.get(attributes__check_id="iam_root_mfa_enabled")
    assert crit.severity == "critical"


@pytest.mark.integration
@pytest.mark.django_db
def test_spine_ingest_dedups_duplicate_records_within_a_scan(workspace_factory, django_capture_on_commit_callbacks):
    """Two identical records in one OCSF output share a fingerprint → ONE SSOT row
    (the legacy per-scan get_or_create dedup, now provided by SSOT identity)."""
    from infrastructure.persistence.findings.models import Finding

    ws = workspace_factory()
    records = _records()
    dup = [*records, records[0]]
    with django_capture_on_commit_callbacks(execute=True):
        _spine_ingest(ws, dup)

    s3 = Finding.objects.filter(workspace=ws, attributes__check_id="s3_bucket_public_access")
    assert s3.count() == 1
