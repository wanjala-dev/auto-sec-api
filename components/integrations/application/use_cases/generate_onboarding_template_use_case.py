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
from dataclasses import dataclass


@dataclass
class GenerateOnboardingTemplateUseCase:
    """Builds the CloudFormation template / Terraform module for a connection."""

    _vendor_account_resolver: Callable[[], str]

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

output "autosec_role_arn" {{
  value = aws_iam_role.autosec_audit.arn
}}
'''
