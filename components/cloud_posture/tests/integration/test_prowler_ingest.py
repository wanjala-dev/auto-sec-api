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
    ingest_prowler_scan,
    parse_prowler_ocsf,
)
from infrastructure.persistence.cloud_posture.models import CloudPostureFinding

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


@pytest.mark.integration
@pytest.mark.django_db
def test_ingest_persists_scan_and_actionable_findings(workspace_factory):
    ws = workspace_factory()

    scan = ingest_prowler_scan(workspace_id=ws.id, account_id="123456789012", records=_records())

    assert scan.total_checks == 3
    assert scan.passed_count == 1
    assert scan.failed_count == 2

    findings = CloudPostureFinding.objects.filter(scan=scan)
    # Only the two non-PASS checks are persisted as findings.
    assert findings.count() == 2
    assert set(findings.values_list("check_id", flat=True)) == {
        "s3_bucket_public_access",
        "iam_root_mfa_enabled",
    }
    crit = findings.get(check_id="iam_root_mfa_enabled")
    assert crit.severity == "critical"
    assert crit.workspace_id == ws.id


@pytest.mark.integration
@pytest.mark.django_db
def test_ingest_dedups_within_scan(workspace_factory):
    ws = workspace_factory()
    records = _records()
    # Duplicate the S3 FAIL record — same (check_id, resource_uid).
    dup = [*records, records[0]]

    scan = ingest_prowler_scan(workspace_id=ws.id, account_id="123456789012", records=dup)

    assert CloudPostureFinding.objects.filter(scan=scan, check_id="s3_bucket_public_access").count() == 1
