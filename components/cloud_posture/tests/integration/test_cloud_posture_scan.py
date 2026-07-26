"""Tests for the role-template widening + the Prowler scan orchestration.

Template tests are pure (no DB). The orchestration test mocks the two live
seams (assume-role + Prowler run) so it verifies the wiring without AWS.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from components.cloud_posture.infrastructure.tasks.cloud_posture_tasks import (
    run_prowler_scan_for_account,
)
from components.integrations.application.use_cases.generate_onboarding_template_use_case import (
    GenerateOnboardingTemplateUseCase,
)
from infrastructure.persistence.cloud_posture.models import CloudPostureScan
from infrastructure.persistence.integrations.models import AwsOrganizationConnection

_SECURITY_AUDIT = "arn:aws:iam::aws:policy/SecurityAudit"
_VIEW_ONLY = "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess"

_CREDS = {"AccessKeyId": "AKIA", "SecretAccessKey": "secret", "SessionToken": "token"}
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
    }
]


def _use_case():
    return GenerateOnboardingTemplateUseCase(_vendor_account_resolver=lambda: "999999999999")


def _conn_ns(**overrides):
    base = {
        "id": uuid.uuid4(),
        "role_name": "AutoSecAuditRole",
        "external_id": "ext-123",
        "org_wide": False,
        "management_account_id": "123456789012",
        "organization_id": "o-abc123",
        "regions": [],
        "name": "AWS Org",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.unit
def test_cloudformation_attaches_prowler_managed_policies():
    blob = json.dumps(_use_case().cloudformation(_conn_ns()))
    assert _SECURITY_AUDIT in blob
    assert _VIEW_ONLY in blob


@pytest.mark.unit
def test_cloudformation_org_wide_member_role_also_gets_policies():
    # Org-wide deep-copies the role into the member StackSet — both must carry it.
    blob = json.dumps(_use_case().cloudformation(_conn_ns(org_wide=True)))
    assert blob.count(_SECURITY_AUDIT) >= 2


@pytest.mark.unit
def test_terraform_attaches_prowler_managed_policies():
    tf = _use_case().terraform(_conn_ns())
    assert _SECURITY_AUDIT in tf
    assert _VIEW_ONLY in tf
    assert "aws_iam_role_policy_attachment" in tf


@pytest.mark.integration
@pytest.mark.django_db
def test_run_prowler_scan_for_account_assumes_runs_and_ingests(workspace_factory):
    ws = workspace_factory()
    conn = AwsOrganizationConnection.objects.create(
        workspace=ws,
        management_account_id="123456789012",
        external_id=f"ext-{uuid.uuid4().hex[:12]}",
        role_name="AutoSecAuditRole",
    )

    target = "components.cloud_posture.infrastructure.tasks.cloud_posture_tasks"
    creds_port = MagicMock()
    creds_port.assume_role.return_value = _CREDS
    with (
        patch(f"{target}.get_aws_credentials_port", return_value=creds_port),
        # run_prowler now runs behind the ProwlerScanner ScannerPort adapter (Phase 4);
        # patch it at its source so the scanner + records_to_scan_result still execute.
        patch(
            "components.cloud_posture.infrastructure.adapters.prowler_runner.run_prowler",
            return_value=_RECORDS,
        ) as m_run,
    ):
        result = run_prowler_scan_for_account(str(conn.id), "123456789012")

    assert result["success"] is True
    assert result["failed"] == 1
    creds_port.assume_role.assert_called_once()
    m_run.assert_called_once()
    scan = CloudPostureScan.objects.get(id=result["scan_id"])
    assert scan.workspace_id == ws.id
    assert scan.account_id == "123456789012"
    assert scan.connection_id == conn.id


@pytest.mark.integration
@pytest.mark.django_db
def test_run_prowler_scan_for_account_missing_connection_is_safe():
    result = run_prowler_scan_for_account(str(uuid.uuid4()), "123456789012")
    assert result["success"] is False
    assert result["error"] == "connection_not_found"
