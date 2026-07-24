"""Integration tests for the CloudPostureDetector.

Ingests Prowler findings, then verifies the detector emits one board finding per
actionable check with the right severity→impact mapping and dedup key.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from components.agents.domain.detectors.base import DetectorContext
from components.agents.infrastructure.adapters.actions.detectors.cloud_posture import (
    CloudPostureDetector,
)
from components.cloud_posture.infrastructure.services.prowler_ingest_service import (
    ingest_prowler_scan,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_RECORDS = [
    {
        "metadata": {"event_code": "s3_bucket_public_access"},
        "severity": "High",
        "status_code": "FAIL",
        "finding_info": {"uid": "u1", "title": "S3 bucket is public"},
        "resources": [
            {
                "uid": "arn:aws:s3:::b",
                "name": "b",
                "type": "AwsS3Bucket",
                "region": "us-east-1",
                "group": {"name": "s3"},
            }
        ],
        "cloud": {"account": {"uid": "123456789012"}, "region": "us-east-1"},
        "remediation": {"desc": "Block public access."},
    },
    {
        "metadata": {"event_code": "iam_root_mfa_enabled"},
        "severity": "Critical",
        "status_code": "FAIL",
        "finding_info": {"uid": "u2", "title": "Root MFA disabled"},
        "resources": [
            {
                "uid": "arn:aws:iam::123456789012:root",
                "name": "root",
                "type": "AwsIamUser",
                "region": "us-east-1",
                "group": {"name": "iam"},
            }
        ],
        "cloud": {"account": {"uid": "123456789012"}, "region": "us-east-1"},
        "remediation": {"desc": "Enable MFA on root."},
    },
]


def _ctx(ws):
    return DetectorContext(workspace_id=str(ws.id), teammate_id="t", run_at=timezone.now(), last_run_at=None)


def test_detector_emits_board_findings_for_actionable_cspm(workspace_factory):
    ws = workspace_factory()
    ingest_prowler_scan(workspace_id=ws.id, account_id="123456789012", records=_RECORDS)

    results = list(CloudPostureDetector().execute(_ctx(ws)))

    assert len(results) == 2
    by_check = {r.payload["check_id"]: r for r in results}
    assert by_check["iam_root_mfa_enabled"].metadata["impact_score"] == 90
    assert by_check["s3_bucket_public_access"].metadata["impact_score"] == 70
    # Worst-first so the cap keeps criticals.
    assert results[0].payload["severity"] == "critical"

    s3 = by_check["s3_bucket_public_access"]
    assert s3.action_type == "cloud_posture"
    assert s3.agent_type is None
    assert s3.payload["lookup_key"] == "cloud_posture:123456789012:s3_bucket_public_access:arn:aws:s3:::b"


def test_detector_should_run_leases_to_hourly(workspace_factory):
    ws = workspace_factory()
    detector = CloudPostureDetector()
    ctx = _ctx(ws)

    assert detector.should_run(ctx) is True
    assert detector.should_run(ctx) is False
