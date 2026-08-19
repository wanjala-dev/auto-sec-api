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

        from components.integrations.application.providers.aws_credentials_provider import (
            get_aws_credentials_port,
        )

        # Live dry-run assume (uncached) through the single credential-vending
        # seam — verification must prove the role works right now, not reuse a
        # warm session.
        assumed = get_aws_credentials_port().assume_role(
            account_id=management_account_id,
            role_name=role_name,
            external_id=external_id,
            session_name="autosec-verify",
            duration_seconds=900,
            use_cache=False,
        )

        # The management account is always scannable once the role assumes — a
        # single-account (non-org) customer IS this one account, and org-wide
        # discovery lists it too. Seed it so a connected connection never has
        # zero scannable accounts (which the scan scheduler would silently skip).
        discovered: dict[str, str] = {management_account_id: ""}
        # ``org_walked`` says whether ``accounts`` is the AUTHORITATIVE membership
        # of the organization or merely what we could see. It is the difference
        # between "these three accounts left the org" and "we were denied the
        # listing, so we only know about the management account" — and the
        # reconciler needs it, because suspending every account of a customer's
        # org on a transient AccessDenied would be a self-inflicted outage.
        result: dict = {"organization_id": "", "accounts": [], "org_walked": False}

        if discover:
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
                            discovered[acct["Id"]] = acct.get("Name", "")
                # Set only after the FULL pagination completed — a walk that
                # died halfway is not an authoritative membership list.
                result["org_walked"] = True
            except org.exceptions.AccessDeniedException:
                # Single-account (non-org) customer — role works, no org to walk.
                logger.info(
                    "aws_org_discovery_denied account=%s (treating as single-account)",
                    management_account_id,
                )

        result["accounts"] = [{"id": aid, "name": name} for aid, name in discovered.items()]
        return result
