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
from components.cloud_posture.tests._prowler_backend_stub import RecordsBackend
from components.integrations.application.use_cases.generate_onboarding_template_use_case import (
    GenerateOnboardingTemplateUseCase,
)

# The ProwlerScanner now runs the engine on a ScanExecutionBackend (ADR 0006); patch the
# backend provider so the real scanner + records_to_scan_result execute against canned records.
_BACKEND_PROVIDER = "components.scanning.application.providers.execution_backend_provider.build_execution_backend"
# The generic spine task's default AWS assume-role vend (the single token-vending seam).
_CREDS_PROVIDER = "components.integrations.application.providers.aws_credentials_provider.get_aws_credentials_port"
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
def test_spine_scan_assumes_runs_and_ingests(workspace_factory):
    """The generic spine task drives the real ProwlerScanner: creds vended through
    the single AWS seam, the engine backend invoked once, the run recorded as a
    ScanRun row."""
    from components.scanning.infrastructure.tasks.scan_tasks import run_scan

    ws = workspace_factory()
    conn = AwsOrganizationConnection.objects.create(
        workspace=ws,
        management_account_id="123456789012",
        external_id=f"ext-{uuid.uuid4().hex[:12]}",
        role_name="AutoSecAuditRole",
    )

    creds_port = MagicMock()
    creds_port.assume_role.return_value = _CREDS
    backend = RecordsBackend(_RECORDS)
    with (
        patch(_CREDS_PROVIDER, return_value=creds_port),
        patch(_BACKEND_PROVIDER, return_value=backend),
    ):
        result = run_scan(
            source="cloud_posture.prowler",
            workspace_id=str(ws.id),
            target_ref="123456789012",
            connection_id=str(conn.id),
            account_id="123456789012",
            trigger="manual",
        )

    assert result["success"] is True
    assert result["findings"] == 1
    creds_port.assume_role.assert_called_once()
    assert len(backend.calls) == 1
    from infrastructure.persistence.scanning.models import ScanRun

    run = ScanRun.objects.get(workspace=ws, source="cloud_posture.prowler", account_id="123456789012")
    assert run.connection_id == conn.id
    assert run.status == ScanRun.Status.COMPLETED


@pytest.mark.integration
@pytest.mark.django_db
def test_legacy_task_shim_forwards_onto_the_spine(workspace_factory):
    """Lossless-deploy shim: a pre-spine broker message re-routes through the
    gated spine dispatch instead of poisoning (or running the dead pipeline)."""
    ws = workspace_factory()
    conn = AwsOrganizationConnection.objects.create(
        workspace=ws,
        management_account_id="123456789012",
        external_id=f"ext-{uuid.uuid4().hex[:12]}",
        role_name="AutoSecAuditRole",
    )

    with patch("components.scanning.application.providers.scan_dispatch_provider.dispatch_scan") as m_dispatch:
        result = run_prowler_scan_for_account(str(conn.id), "123456789012")

    assert result["success"] is True
    assert result["enqueued"] is True
    kwargs = m_dispatch.call_args.kwargs
    assert kwargs["source"] == "cloud_posture.prowler"
    assert kwargs["trigger"] == "schedule"


@pytest.mark.integration
@pytest.mark.django_db
def test_run_prowler_scan_for_account_missing_connection_is_safe():
    result = run_prowler_scan_for_account(str(uuid.uuid4()), "123456789012")
    assert result["success"] is False
    assert result["error"] == "connection_not_found"


@pytest.mark.integration
@pytest.mark.django_db
def test_failed_scan_publishes_scan_failed_event(workspace_factory, monkeypatch):
    """The fail-loud path emits ``ScanFailed`` so the funnel can alert that
    coverage is degraded (ADR 0016 ``soc.scan_failed``) — with a per-attempt
    identity and a coarse redaction-safe reason, never the raw exception."""
    from components.shared_kernel.domain.events import ScanFailed
    from components.shared_kernel.infrastructure.adapters import celery_event_publisher as pub_mod

    ws = workspace_factory()
    conn = AwsOrganizationConnection.objects.create(
        workspace=ws,
        management_account_id="123456789012",
        external_id=f"ext-{uuid.uuid4().hex[:12]}",
        role_name="AutoSecAuditRole",
    )

    from components.scanning.infrastructure.tasks.scan_tasks import run_scan

    published = []
    monkeypatch.setattr(pub_mod.CeleryEventPublisher, "publish", lambda self, event: published.append(event))

    creds_port = MagicMock()
    creds_port.assume_role.side_effect = RuntimeError("AccessDenied: arn:aws:iam::123:role/secret")
    with patch(_CREDS_PROVIDER, return_value=creds_port):
        result = run_scan(
            source="cloud_posture.prowler",
            workspace_id=str(ws.id),
            target_ref="123456789012",
            connection_id=str(conn.id),
            account_id="123456789012",
            trigger="manual",
        )

    assert result == {"success": False, "error": "scan_failed"}
    failed = [e for e in published if isinstance(e, ScanFailed)]
    assert len(failed) == 1
    event = failed[0]
    assert event.workspace_id == ws.id
    assert event.source == "cloud_posture.prowler"
    assert event.engine == "prowler"
    assert event.account_id == "123456789012"
    assert event.run_id, "a per-attempt identity is required so recurring failures re-alert"
    assert event.reason == "scan engine failure"
    assert "AccessDenied" not in event.reason

    # Even a credential-vend failure (bad account / revoked role) leaves an honest
    # FAILED run row — previously a failed CSPM scan left no record at all.
    from infrastructure.persistence.scanning.models import ScanRun

    run = ScanRun.objects.get(workspace=ws, source="cloud_posture.prowler", target_ref="123456789012")
    assert run.status == ScanRun.Status.FAILED
    assert run.error
