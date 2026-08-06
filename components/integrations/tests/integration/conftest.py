"""Shared fixtures for the integrations API integration tests.

Provides the workspace + owner an operator hits when wiring AWS onboarding, and
two seam stubs so the connect → verify → scan chain can run hermetically (no live
AWS, no Prowler install):

* ``stub_org_verification`` — patches the ``OrgVerificationPort`` implementation
  (``StsOrgAdapter.verify_and_discover``) so ``/verify/`` succeeds and discovers a
  fake org + member accounts (→ ``AwsAccountLink`` rows) without STS.
* ``stub_scan_execution`` — patches BOTH scan seams the eager Celery task reaches:
  the credential-vending port (so ``assume_role`` returns canned creds) and the
  ``ScanExecutionBackend`` provider (so the REAL ``ProwlerScanner`` +
  ``records_to_scan_result`` run against canned OCSF records via ``RecordsBackend``).

DRY: reuses the root ``workspace_factory``/``user_factory`` and the cloud_posture
``RecordsBackend`` stub rather than re-rolling scanner machinery.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest import mock

import pytest

from components.cloud_posture.tests._prowler_backend_stub import RecordsBackend

# The OrgVerificationPort implementation the AWS connection provider wires in.
_STS_ADAPTER = "components.integrations.infrastructure.adapters.sts_org_adapter.StsOrgAdapter"
# The two seams the eager run_prowler_scan_for_account task reaches out through.
_BACKEND_PROVIDER = "components.scanning.application.providers.execution_backend_provider.build_execution_backend"
_TASK_CREDS = "components.cloud_posture.infrastructure.tasks.cloud_posture_tasks.get_aws_credentials_port"

# One canned OCSF FAIL record — Prowler's shape (metadata.event_code + a resource +
# cloud.account.uid). Parsed by the real records_to_scan_result into one actionable
# NormalizedFinding, dual-written into the Finding SSOT.
DEFAULT_OCSF_RECORDS: list[dict] = [
    {
        "metadata": {"event_code": "s3_bucket_public_access"},
        "severity": "High",
        "status_code": "FAIL",
        "finding_info": {"uid": "u-e2e-1", "title": "S3 bucket is public"},
        "resources": [
            {
                "uid": "arn:aws:s3:::e2e-public-bucket",
                "name": "e2e-public-bucket",
                "type": "AwsS3Bucket",
                "region": "us-east-1",
                "group": {"name": "s3"},
            }
        ],
        "cloud": {"account": {"uid": "123456789012"}, "region": "us-east-1"},
        "remediation": {"desc": "Enable S3 Block Public Access."},
    }
]


@pytest.fixture
def integrations_workspace(workspace_factory):
    """A workspace + its owner. The owner authorizes ``manage_integrations`` structurally
    (workspace ownership short-circuits the permission gate), so no membership seeding is
    needed for the happy path."""
    ws = workspace_factory()
    return SimpleNamespace(workspace=ws, owner=ws.workspace_owner)


@contextlib.contextmanager
def _stub_org_verification(*, accounts=None, organization_id="o-autosectest"):
    """Patch the OrgVerificationPort so ``/verify/`` succeeds without STS.

    ``accounts`` defaults to a single member account, mirroring what
    ``organizations:ListAccounts`` would return; each becomes an ``AwsAccountLink``.
    """
    resolved = accounts if accounts is not None else [{"id": "123456789012", "name": "Prod"}]
    with mock.patch(
        f"{_STS_ADAPTER}.verify_and_discover",
        return_value={"organization_id": organization_id, "accounts": resolved},
    ) as patched:
        yield patched


@contextlib.contextmanager
def _stub_scan_execution(records=None):
    """Patch both scan seams; yields the ``RecordsBackend`` for spec assertions."""
    backend = RecordsBackend(records if records is not None else DEFAULT_OCSF_RECORDS)
    creds_port = mock.MagicMock()
    creds_port.assume_role.return_value = {
        "AccessKeyId": "AKIA-e2e",
        "SecretAccessKey": "secret-e2e",
        "SessionToken": "token-e2e",
    }
    with (
        mock.patch(_BACKEND_PROVIDER, return_value=backend),
        mock.patch(_TASK_CREDS, return_value=creds_port),
    ):
        yield backend


@pytest.fixture
def aws_connection_factory():
    """Build a CONNECTED ``AwsOrganizationConnection`` for a workspace — the
    prerequisite row for log sources / scans. Shared by the log-source and
    backbone chain suites (dry-reuse: one canonical builder, not one per module)."""

    def _create(workspace, owner=None, **overrides):
        from infrastructure.persistence.integrations.models import AwsOrganizationConnection

        defaults = dict(
            workspace=workspace,
            management_account_id="123456789012",
            role_name="AutoSecAuditRole",
            external_id=f"ext-{workspace.id}",
            status=AwsOrganizationConnection.Status.CONNECTED,
            created_by=owner or workspace.workspace_owner,
        )
        defaults.update(overrides)
        return AwsOrganizationConnection.objects.create(**defaults)

    return _create


@pytest.fixture
def stub_org_verification():
    """Return the ``_stub_org_verification`` context manager (a fixture so tests get it
    without importing from conftest)."""
    return _stub_org_verification


@pytest.fixture
def stub_scan_execution():
    """Return the ``_stub_scan_execution`` context manager."""
    return _stub_scan_execution
