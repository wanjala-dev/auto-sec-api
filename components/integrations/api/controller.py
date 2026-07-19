"""AWS Organization onboarding endpoints (Settings ▸ Integrations).

Flow (the pattern production security vendors use):
1. ``POST /integrations/aws/`` — creates the connection and GENERATES the
   ``external_id`` (vendor-side, never customer-chosen — confused-deputy
   defense per AWS SEC03-BP09).
2. ``GET  /integrations/aws/<id>/cloudformation/`` — returns the generated
   CloudFormation template the customer launches in their MANAGEMENT account.
   With ``org_wide`` it includes a StackSet using **service-managed
   permissions + auto-deployment**, so every current and future member
   account gets the audit role automatically (no per-account tickets, drift
   detection catches tampering).
3. ``POST /integrations/aws/<id>/verify/`` — assume-role dry-run through the
   management role; on success discovers member accounts
   (``organizations:ListAccounts``) into AwsAccountLink rows. Verification is
   per-account so one broken account degrades — never breaks — the org.

The role's inline policy is LEAST-PRIVILEGE read: CloudTrail S3 objects, the
notification SQS queue, org account listing (management only), and scoped
KMS decrypt for encrypted trails.
"""

from __future__ import annotations

import json
import logging
import secrets

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from components.membership.api.permissions import has_workspace_permission

logger = logging.getLogger(__name__)

CanManageIntegrations = has_workspace_permission("manage_integrations")


# Our platform's AWS account — the ONLY principal the customer role trusts.
# Resolved from settings/env at request time (never hardcoded per-tenant).
def _vendor_account_id() -> str:
    from django.conf import settings

    acct = getattr(settings, "AUTOSEC_VENDOR_AWS_ACCOUNT_ID", "") or __import__("os").environ.get(
        "AUTOSEC_VENDOR_AWS_ACCOUNT_ID", ""
    )
    if not (acct.isdigit() and len(acct) == 12):
        # NEVER emit a placeholder into a customer trust policy — a role
        # trusting a wrong/nonexistent account is a silent onboarding break.
        raise RuntimeError(
            "AUTOSEC_VENDOR_AWS_ACCOUNT_ID is not configured — set the "
            "platform's AWS account id before generating onboarding templates."
        )
    return acct


def _serialize(conn) -> dict:
    return {
        "id": str(conn.id),
        "name": conn.name,
        "management_account_id": conn.management_account_id,
        "organization_id": conn.organization_id,
        "role_name": conn.role_name,
        "external_id": conn.external_id,
        "org_wide": conn.org_wide,
        "regions": conn.regions,
        "trail_s3_bucket": conn.trail_s3_bucket,
        "sqs_queue_url": conn.sqs_queue_url,
        "status": conn.status,
        "last_verified_at": conn.last_verified_at.isoformat() if conn.last_verified_at else None,
        "last_error": conn.last_error,
        "accounts": [
            {
                "account_id": a.account_id,
                "account_name": a.account_name,
                "status": a.status,
            }
            for a in conn.accounts.all()[:200]
        ],
    }


def build_cloudformation_template(conn) -> dict:
    """The customer-side template: audit role (+ optional org StackSet)."""
    vendor = _vendor_account_id()
    role = {
        "Type": "AWS::IAM::Role",
        "Properties": {
            "RoleName": conn.role_name,
            "AssumeRolePolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": f"arn:aws:iam::{vendor}:root"},
                        "Action": "sts:AssumeRole",
                        "Condition": {"StringEquals": {"sts:ExternalId": conn.external_id}},
                    }
                ],
            },
            "Policies": [
                {
                    "PolicyName": "AutoSecAuditReadOnly",
                    "PolicyDocument": {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Sid": "TrailObjects",
                                "Effect": "Allow",
                                "Action": ["s3:GetObject", "s3:GetBucketLocation", "s3:ListBucket"],
                                "Resource": ["arn:aws:s3:::*cloudtrail*", "arn:aws:s3:::*cloudtrail*/*"],
                            },
                            {
                                "Sid": "TrailQueue",
                                "Effect": "Allow",
                                "Action": [
                                    "sqs:ReceiveMessage",
                                    "sqs:DeleteMessage",
                                    "sqs:GetQueueAttributes",
                                ],
                                "Resource": "*",
                                "Condition": {"StringLike": {"aws:ResourceTag/autosec": "*"}},
                            },
                            {
                                "Sid": "OrgDiscovery",
                                "Effect": "Allow",
                                "Action": ["organizations:ListAccounts", "organizations:DescribeOrganization"],
                                "Resource": "*",
                            },
                            {
                                "Sid": "TrailKms",
                                "Effect": "Allow",
                                "Action": ["kms:Decrypt"],
                                "Resource": "*",
                                "Condition": {"StringLike": {"kms:ViaService": "s3.*.amazonaws.com"}},
                            },
                        ],
                    },
                }
            ],
        },
    }
    resources = {"AutoSecAuditRole": role}
    if conn.org_wide:
        # Member-account role rollout: service-managed StackSet with
        # auto-deployment — future accounts are covered automatically.
        member_template = {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Resources": {
                "AutoSecAuditRole": json.loads(json.dumps(role))  # same role, member scope
            },
        }
        # Members don't need org discovery.
        member_template["Resources"]["AutoSecAuditRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"] = [
            s
            for s in member_template["Resources"]["AutoSecAuditRole"]["Properties"]["Policies"][0]["PolicyDocument"][
                "Statement"
            ]
            if s["Sid"] != "OrgDiscovery"
        ]
        resources["AutoSecOrgStackSet"] = {
            "Type": "AWS::CloudFormation::StackSet",
            "Properties": {
                "StackSetName": f"AutoSec-{str(conn.id)[:8]}",
                "PermissionModel": "SERVICE_MANAGED",
                "AutoDeployment": {"Enabled": True, "RetainStacksOnAccountRemoval": False},
                "Capabilities": ["CAPABILITY_NAMED_IAM"],
                "StackInstancesGroup": [
                    {
                        "DeploymentTargets": {"OrganizationalUnitIds": [{"Ref": "RootOuId"}]},
                        "Regions": ["us-east-1"],
                    }
                ],
                "TemplateBody": json.dumps(member_template),
            },
        }
    template = {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "Auto-Sec read-only audit access (CloudTrail ingestion).",
        "Parameters": (
            {"RootOuId": {"Type": "String", "Description": "Root OU id (r-xxxx) for org-wide rollout."}}
            if conn.org_wide
            else {}
        ),
        "Resources": resources,
    }
    return template


def build_terraform_module(conn) -> str:
    """Terraform equivalent for IaC-first customers (same role + trust).

    Single-account: the audit role in the management account. Org-wide: the
    customer applies the same module per account via their own orchestration
    (or uses our CloudFormation StackSet path — service-managed StackSets are
    a CFN-native capability, which is why vendors ship BOTH formats).
    """
    vendor = _vendor_account_id()
    return f'''variable "external_id" {{
  description = "Auto-Sec vendor-generated external id (confused-deputy token)"
  type        = string
  default     = "{conn.external_id}"
}}

resource "aws_iam_role" "autosec_audit" {{
  name = "{conn.role_name}"

  assume_role_policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [{{
      Effect    = "Allow"
      Principal = {{ AWS = "arn:aws:iam::{vendor}:root" }}
      Action    = "sts:AssumeRole"
      Condition = {{ StringEquals = {{ "sts:ExternalId" = var.external_id }} }}
    }}]
  }})
}}

resource "aws_iam_role_policy" "autosec_audit_read" {{
  name = "AutoSecAuditReadOnly"
  role = aws_iam_role.autosec_audit.id

  policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [
      {{
        Sid      = "TrailObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetBucketLocation", "s3:ListBucket"]
        Resource = ["arn:aws:s3:::*cloudtrail*", "arn:aws:s3:::*cloudtrail*/*"]
      }},
      {{
        Sid      = "TrailQueue"
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = "*"
        Condition = {{ StringLike = {{ "aws:ResourceTag/autosec" = "*" }} }}
      }},
      {{
        Sid      = "OrgDiscovery"
        Effect   = "Allow"
        Action   = ["organizations:ListAccounts", "organizations:DescribeOrganization"]
        Resource = "*"
      }},
      {{
        Sid      = "TrailKms"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
        Condition = {{ StringLike = {{ "kms:ViaService" = "s3.*.amazonaws.com" }} }}
      }}
    ]
  }})
}}

output "autosec_role_arn" {{
  value = aws_iam_role.autosec_audit.arn
}}
'''


class AwsConnectionListCreateView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-aws"

    def get(self, request, workspace_id):
        from infrastructure.persistence.integrations.models import AwsOrganizationConnection

        conns = AwsOrganizationConnection.objects.filter(workspace_id=workspace_id).prefetch_related("accounts")
        return Response({"success": True, "data": [_serialize(c) for c in conns]})

    def post(self, request, workspace_id):
        from infrastructure.persistence.integrations.models import AwsOrganizationConnection

        mgmt = (request.data.get("management_account_id") or "").strip()
        if not (mgmt.isdigit() and len(mgmt) == 12):
            return Response(
                {"success": False, "error": "management_account_id must be a 12-digit AWS account id."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        conn, created = AwsOrganizationConnection.objects.get_or_create(
            workspace_id=workspace_id,
            management_account_id=mgmt,
            defaults={
                "name": request.data.get("name") or "AWS Organization",
                "role_name": request.data.get("role_name") or "AutoSecAuditRole",
                "org_wide": bool(request.data.get("org_wide", True)),
                "regions": request.data.get("regions") or [],
                "trail_s3_bucket": request.data.get("trail_s3_bucket") or "",
                "sqs_queue_url": request.data.get("sqs_queue_url") or "",
                # Vendor-generated, URL-safe, unique — the confused-deputy token.
                "external_id": f"autosec-{secrets.token_urlsafe(24)}",
                "created_by": request.user,
            },
        )
        return Response(
            {"success": True, "data": _serialize(conn), "created": created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class AwsConnectionTemplateView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-aws-cloudformation"

    def get(self, request, workspace_id, connection_id):
        from infrastructure.persistence.integrations.models import AwsOrganizationConnection

        conn = AwsOrganizationConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()
        if conn is None:
            return Response({"success": False, "error": "Connection not found."}, status=404)
        fmt = (request.query_params.get("fmt") or "cloudformation").lower()
        if fmt == "terraform":
            return Response({"success": True, "format": "terraform", "data": build_terraform_module(conn)})
        return Response(
            {
                "success": True,
                "format": "cloudformation",
                "data": build_cloudformation_template(conn),
            }
        )


class AwsConnectionVerifyView(APIView):
    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-aws-verify"

    def post(self, request, workspace_id, connection_id):
        from django.utils import timezone

        from infrastructure.persistence.integrations.models import (
            AwsAccountLink,
            AwsOrganizationConnection,
        )

        conn = AwsOrganizationConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()
        if conn is None:
            return Response({"success": False, "error": "Connection not found."}, status=404)

        from components.integrations.infrastructure.adapters.sts_org_adapter import (
            StsOrgAdapter,
        )

        adapter = StsOrgAdapter()
        try:
            result = adapter.verify_and_discover(
                management_account_id=conn.management_account_id,
                role_name=conn.role_name,
                external_id=conn.external_id,
                discover=conn.org_wide,
            )
        except Exception as exc:
            logger.exception(
                "aws_connection_verify_failed connection_id=%s workspace_id=%s",
                connection_id,
                workspace_id,
            )
            conn.status = AwsOrganizationConnection.Status.ERROR
            conn.last_error = str(exc)[:2000]
            conn.save(update_fields=["status", "last_error", "updated_at"])
            return Response(
                {"success": False, "error": conn.last_error},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        conn.status = AwsOrganizationConnection.Status.CONNECTED
        conn.organization_id = result.get("organization_id") or conn.organization_id
        conn.last_verified_at = timezone.now()
        conn.last_error = ""
        conn.save()
        for acct in result.get("accounts") or []:
            AwsAccountLink.objects.update_or_create(
                connection=conn,
                account_id=acct["id"],
                defaults={
                    "account_name": acct.get("name") or "",
                    "status": AwsAccountLink.Status.DISCOVERED,
                },
            )
        return Response({"success": True, "data": _serialize(conn)})


class FindingOpenDraftPrView(APIView):
    """POST /integrations/workspaces/<ws>/findings/<task_id>/open-draft-pr/

    The rung-1 HITL path for the triage agent's draft-PR capability: a human
    operator approves, and the use case (the single choke point for EVERY
    precondition — installed connection, repo allowlist, finding triaged and
    not needs_human, agent capability enabled) opens the draft PR. Thin:
    parse → use case → serialize. Idempotent — a finding that already has a
    draft PR returns the existing URL with 200.
    """

    permission_classes = (permissions.IsAuthenticated, CanManageIntegrations)
    name = "integrations-finding-open-draft-pr"

    _REASON_STATUS = {
        "finding_not_found": status.HTTP_404_NOT_FOUND,
        "no_github_connection": status.HTTP_409_CONFLICT,
        "connection_not_connected": status.HTTP_409_CONFLICT,
        "no_github_token": status.HTTP_409_CONFLICT,
        "repo_not_allowlisted": status.HTTP_409_CONFLICT,
        "finding_not_triaged": status.HTTP_409_CONFLICT,
        "finding_needs_human": status.HTTP_409_CONFLICT,
        "capability_disabled": status.HTTP_403_FORBIDDEN,
        "no_candidate_path": status.HTTP_422_UNPROCESSABLE_ENTITY,
        "no_grounded_patch": status.HTTP_422_UNPROCESSABLE_ENTITY,
    }

    def post(self, request, workspace_id, task_id):
        from components.integrations.application.ports.github_pr_port import GitHubApiError
        from components.integrations.application.providers.github_pr_provider import (
            get_open_draft_pr_use_case,
        )
        from components.integrations.application.use_cases.open_draft_pr_use_case import (
            DraftPrPreconditionError,
        )

        try:
            result = get_open_draft_pr_use_case().execute(
                workspace_id=str(workspace_id),
                task_id=str(task_id),
                performed_by=str(request.user.id),
                repo=(request.data.get("repo") or "").strip() or None,
            )
        except DraftPrPreconditionError as exc:
            return Response(
                {"success": False, "reason": exc.reason, "error": str(exc)},
                status=self._REASON_STATUS.get(exc.reason, status.HTTP_400_BAD_REQUEST),
            )
        except GitHubApiError as exc:
            logger.exception("open_draft_pr_endpoint github error workspace_id=%s task_id=%s", workspace_id, task_id)
            return Response(
                {"success": False, "reason": "github_api_error", "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "success": True,
                "data": {
                    "url": result.url,
                    "repo": result.repo,
                    "branch": result.branch,
                    "created": result.created,
                },
            },
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class AwsConnectionLogStreamView(APIView):
    """GET /integrations/workspaces/<ws>/aws/<id>/logstream/

    Recent parsed records from the connection's shipped logs — feeds the HUD
    LOG STREAM card. The role-assumed S3 read is EXPENSIVE relative to a UI
    poll, so the scan result is cached for 60s per connection; the card polls
    every ~30s and mostly hits cache. Read-only; never advances the ingest
    checkpoint (the detect loop owns that cursor).
    """

    permission_classes = (permissions.IsAuthenticated,)
    name = "integrations-aws-logstream"

    def get(self, request, workspace_id, connection_id):
        from django.core.cache import cache

        from infrastructure.persistence.integrations.models import AwsOrganizationConnection

        conn = AwsOrganizationConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()
        if conn is None:
            return Response({"success": False, "error": "Connection not found."}, status=404)

        cache_key = f"logstream:{connection_id}"
        payload = cache.get(cache_key)
        if payload is None:
            from components.integrations.application.log_ingest_service import scan_connection

            try:
                result = scan_connection(conn, max_objects=4, only_new=False)
            except Exception as exc:
                logger.exception("logstream_scan_failed connection_id=%s", connection_id)
                return Response(
                    {"success": False, "error": str(exc)[:300]},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            payload = {
                "records": [
                    {"service": r.service, "level": r.level, "message": r.message[:220]} for r in result.tail[-80:]
                ],
                "by_service": result.by_service,
                "records_parsed": result.records_parsed,
                "errors": len(result.errors),
                # The flagged lines themselves — drives the Anomalies hex
                # glitch + its click-through error list on the HUD.
                "error_records": [
                    {"service": e.service, "level": e.level, "message": e.message[:300]} for e in result.errors[-20:]
                ],
                "newest_key": result.newest_key,
            }
            cache.set(cache_key, payload, 60)
        return Response({"success": True, "data": payload})
