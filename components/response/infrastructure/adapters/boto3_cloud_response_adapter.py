"""boto3 EC2 adapter for the reversible security-group response action.

Performs the real mutation — ``revoke``/``authorize_security_group_ingress`` —
and grounds a proposal against the live group via ``describe_security_group_rules``.
Credentials come from the integrations account-access port (assume the audit
role in the finding's account); the adapter never reads another context's ORM.

Dry-run is AWS-native: boto3's ``DryRun=True`` makes EC2 return the error code
``DryRunOperation`` when the caller *would* be permitted and ``UnauthorizedOperation``
when not — so a dry-run proposal is validated against real IAM without touching
a single rule. That is what lets us default the demo to dry-run and flip real
execution on only once the audit role is granted the (narrow) write permission.
"""

from __future__ import annotations

import logging

from components.integrations.application.providers.aws_account_access_provider import (
    get_aws_account_access_port,
)
from components.response.application.ports.cloud_response_port import CloudResponsePort
from components.response.domain.value_objects.response_action_kind import ResponseActionKind
from components.response.domain.value_objects.response_action_spec import ResponseActionSpec
from components.response.domain.value_objects.response_outcome import ResponseOutcome
from components.response.domain.value_objects.security_group_rule import SecurityGroupRule

logger = logging.getLogger(__name__)


class Boto3CloudResponseAdapter(CloudResponsePort):
    def _ec2_client(self, *, workspace_id: str, account_id: str, region: str):
        creds = get_aws_account_access_port().credentials_for(
            workspace_id=workspace_id,
            account_id=account_id,
            session_name="autosec-response",
            use_cache=False,  # a mutation gets a fresh, un-shared session
        )
        import boto3

        return boto3.client(
            "ec2",
            region_name=region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )

    def apply(self, spec: ResponseActionSpec, *, workspace_id: str, dry_run: bool) -> ResponseOutcome:
        from botocore.exceptions import ClientError

        client = self._ec2_client(
            workspace_id=workspace_id,
            account_id=spec.account_id,
            region=spec.region,
        )
        ip_permissions = spec.rule.to_ip_permissions()
        call = (
            client.revoke_security_group_ingress
            if spec.kind == ResponseActionKind.REVOKE_SG_INGRESS
            else client.authorize_security_group_ingress
        )
        try:
            response = call(GroupId=spec.group_id, IpPermissions=ip_permissions, DryRun=dry_run)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if dry_run and code == "DryRunOperation":
                logger.info("response_dry_run_ok kind=%s group=%s", spec.kind.value, spec.group_id)
                return ResponseOutcome(performed=False, dry_run=True, would_succeed=True, detail={"code": code})
            if dry_run and code == "UnauthorizedOperation":
                logger.warning("response_dry_run_unauthorized group=%s", spec.group_id)
                return ResponseOutcome(
                    performed=False,
                    dry_run=True,
                    would_succeed=False,
                    detail={"code": code},
                    error="the audit role lacks permission to perform this action",
                )
            logger.exception("response_apply_failed kind=%s group=%s code=%s", spec.kind.value, spec.group_id, code)
            return ResponseOutcome(performed=False, dry_run=dry_run, detail={"code": code}, error=str(exc))

        logger.info("response_applied kind=%s group=%s dry_run=%s", spec.kind.value, spec.group_id, dry_run)
        return ResponseOutcome(
            performed=not dry_run,
            dry_run=dry_run,
            would_succeed=True,
            detail={k: v for k, v in response.items() if k != "ResponseMetadata"},
        )

    def find_matching_public_ingress(
        self,
        *,
        workspace_id: str,
        account_id: str,
        region: str,
        group_id: str,
        rule: SecurityGroupRule,
    ) -> SecurityGroupRule | None:
        client = self._ec2_client(workspace_id=workspace_id, account_id=account_id, region=region)
        resp = client.describe_security_group_rules(
            Filters=[{"Name": "group-id", "Values": [group_id]}],
            MaxResults=1000,
        )
        for row in resp.get("SecurityGroupRules", []):
            if row.get("IsEgress"):
                continue
            cidr = row.get("CidrIpv4") or row.get("CidrIpv6") or ""
            candidate = SecurityGroupRule(
                protocol=str(row.get("IpProtocol")),
                from_port=row.get("FromPort"),
                to_port=row.get("ToPort"),
                cidr=cidr,
                description=row.get("Description", "") or "",
            )
            if (
                candidate.is_public
                and candidate.protocol == rule.protocol
                and candidate.from_port == rule.from_port
                and candidate.to_port == rule.to_port
                and candidate.cidr == rule.cidr
            ):
                return candidate
        return None
