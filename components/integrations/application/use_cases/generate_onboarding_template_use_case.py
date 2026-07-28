"""Generate the customer-side onboarding IaC (CloudFormation / Terraform).

Pure document generation: given a connection (role name, external id,
org-wide flag) and the platform's vendor AWS account id, emit the
least-privilege audit-role template the customer launches in their
management account. The vendor account id is injected by the provider
(``resolve_vendor_account_id`` — an infrastructure concern) so this use
case stays settings-free.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from urllib.parse import quote


def _no_template_url() -> str:
    return ""


@dataclass
class GenerateOnboardingTemplateUseCase:
    """Builds the CloudFormation template / Terraform module for a connection."""

    _vendor_account_resolver: Callable[[], str]
    # The public S3 URL of the HOSTED parameterized template — powers the one-click
    # "Launch Stack" quick-create link. Injected (settings-free); "" → no launch link.
    _template_url_resolver: Callable[[], str] = field(default=_no_template_url)

    # ── CloudFormation ───────────────────────────────────────────────────

    def cloudformation(self, conn) -> dict:
        """The customer-side template: audit role (+ optional org StackSet)."""
        vendor = self._vendor_account_resolver()
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
                # AWS-managed read-only policies powering the Prowler CSPM scan
                # (Phase 3). Well-understood, defensible least-privilege — no
                # hand-rolled describe lists. Keep in lockstep with the Terraform
                # generator below (never widen one without the other).
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/SecurityAudit",
                    "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess",
                ],
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
                                    "Action": [
                                        "organizations:ListAccounts",
                                        "organizations:DescribeOrganization",
                                    ],
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
                "Resources": {"AutoSecAuditRole": json.loads(json.dumps(role))},  # same role, member scope
            }
            # Members don't need org discovery.
            member_policy = member_template["Resources"]["AutoSecAuditRole"]["Properties"]["Policies"][0]
            member_policy["PolicyDocument"]["Statement"] = [
                s for s in member_policy["PolicyDocument"]["Statement"] if s["Sid"] != "OrgDiscovery"
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
        return {
            "AWSTemplateFormatVersion": "2010-09-09",
            "Description": "Auto-Sec read-only audit access (CloudTrail ingestion).",
            "Parameters": (
                {"RootOuId": {"Type": "String", "Description": "Root OU id (r-xxxx) for org-wide rollout."}}
                if conn.org_wide
                else {}
            ),
            "Resources": resources,
        }

    # ── One-click Launch Stack (hosted, parameterized) ───────────────────

    def hosted_cloudformation(self) -> dict:
        """The STATIC, parameterized single-account template hosted once (public S3) for the
        one-click quick-create link. Reuses ``cloudformation`` with ExternalId/RoleName as
        CloudFormation ``Ref`` values, so ONE hosted template serves every connection — the
        launch URL just prefills ``param_ExternalId``. (Single-account only; the org-wide
        StackSet path keeps the copy-the-template flow.)"""
        ref = SimpleNamespace(
            external_id={"Ref": "ExternalId"}, role_name={"Ref": "RoleName"}, org_wide=False, id="hosted"
        )
        tmpl = self.cloudformation(ref)
        tmpl["Description"] = "Auto-Sec read-only audit role (assume-role, External-ID protected)."
        tmpl["Parameters"] = {
            "ExternalId": {
                "Type": "String",
                "MinLength": 8,
                "Description": "Your Auto-Sec External ID (shown in the connect wizard) — confused-deputy protection.",
            },
            "RoleName": {
                "Type": "String",
                "Default": "AutoSecAuditRole",
                "Description": "Name for the read-only audit role.",
            },
        }
        return tmpl

    def launch_url(self, conn, region: str = "us-east-1") -> str | None:
        """The CloudFormation quick-create 'Launch Stack' URL — a one-click console deep-link
        that loads the hosted template and prefills this connection's External ID. Returns
        None when no hosted-template URL is configured (the wizard falls back to copy-template).
        The template creates a NAMED IAM role, so the console asks the user to acknowledge
        CAPABILITY_NAMED_IAM (a link cannot pre-check that)."""
        template_url = (self._template_url_resolver() or "").strip()
        if not template_url:
            return None
        query = "&".join(
            [
                f"templateURL={quote(template_url, safe='')}",
                f"stackName={quote(str(conn.role_name), safe='')}",
                f"param_ExternalId={quote(str(conn.external_id), safe='')}",
                f"param_RoleName={quote(str(conn.role_name), safe='')}",
            ]
        )
        return f"https://console.aws.amazon.com/cloudformation/home?region={region}#/stacks/quickcreate?{query}"

    # ── Terraform ────────────────────────────────────────────────────────

    def terraform(self, conn) -> str:
        """Terraform equivalent for IaC-first customers (same role + trust).

        Single-account: the audit role in the management account. Org-wide:
        the customer applies the same module per account via their own
        orchestration (or uses our CloudFormation StackSet path —
        service-managed StackSets are a CFN-native capability, which is why
        vendors ship BOTH formats).
        """
        vendor = self._vendor_account_resolver()
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

# AWS-managed read-only policies powering the Prowler CSPM scan (Phase 3).
# Kept in lockstep with the CloudFormation generator (never widen one alone).
resource "aws_iam_role_policy_attachment" "autosec_security_audit" {{
  role       = aws_iam_role.autosec_audit.name
  policy_arn = "arn:aws:iam::aws:policy/SecurityAudit"
}}

resource "aws_iam_role_policy_attachment" "autosec_view_only" {{
  role       = aws_iam_role.autosec_audit.name
  policy_arn = "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess"
}}

output "autosec_role_arn" {{
  value = aws_iam_role.autosec_audit.arn
}}
'''
