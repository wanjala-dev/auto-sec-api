"""STS assume-role + Organizations discovery adapter (boto3, lazy).

Verification is a DRY-RUN assume of the customer's audit role with our
vendor-generated ExternalId, then (org-wide) ``organizations:ListAccounts``
through that role. Credentials come from the platform's own AWS identity
(env/instance profile) — customer keys are never stored, role-only access.
Assumed credentials are short-lived; callers should treat them as ephemeral
(the ingestion workers cache per-role sessions and refresh before expiry).
"""

from __future__ import annotations

import logging

from components.integrations.application.ports.org_verification_port import (
    OrgVerificationPort,
)

logger = logging.getLogger(__name__)


class StsOrgAdapter(OrgVerificationPort):
    def verify_and_discover(
        self,
        *,
        management_account_id: str,
        role_name: str,
        external_id: str,
        discover: bool = True,
    ) -> dict:
        import boto3

        role_arn = f"arn:aws:iam::{management_account_id}:role/{role_name}"
        sts = boto3.client("sts")
        assumed = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName="autosec-verify",
            ExternalId=external_id,
            DurationSeconds=900,
        )["Credentials"]
        logger.info("aws_role_assumed account=%s role=%s", management_account_id, role_name)

        result: dict = {"organization_id": "", "accounts": []}
        if not discover:
            return result

        org = boto3.client(
            "organizations",
            aws_access_key_id=assumed["AccessKeyId"],
            aws_secret_access_key=assumed["SecretAccessKey"],
            aws_session_token=assumed["SessionToken"],
        )
        try:
            desc = org.describe_organization()["Organization"]
            result["organization_id"] = desc.get("Id", "")
            paginator = org.get_paginator("list_accounts")
            for page in paginator.paginate():
                for acct in page.get("Accounts", []):
                    if acct.get("Status") == "ACTIVE":
                        result["accounts"].append({"id": acct["Id"], "name": acct.get("Name", "")})
        except org.exceptions.AccessDeniedException:
            # Single-account (non-org) customer — role works, no org to walk.
            logger.info(
                "aws_org_discovery_denied account=%s (treating as single-account)",
                management_account_id,
            )
        return result
