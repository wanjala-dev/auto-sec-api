"""STS assume-role credential vending (boto3, lazy) with a per-role session cache.

The single AWS credential-vending seam (the "token vending machine"): the
platform's own identity — workload identity (EC2 instance profile / ECS task
role / EKS IRSA), resolved by boto3's default credential chain — assumes the
customer's read-only audit role with the vendor-generated ExternalId. Assumed
sessions are cached per role ARN and refreshed before expiry.

AWS caps a role-chained session at 1h when the base identity is itself an
assumed role, so we never request longer than ``_MAX_DURATION_SECONDS`` and
never hand back a cached session within ``_REFRESH_MARGIN`` of its expiry.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from components.integrations.application.ports.aws_role_credentials_port import (
    AwsRoleCredentialsPort,
)

logger = logging.getLogger(__name__)

# Refresh a cached session this long before its STS expiry — comfortably inside
# the 1h role-chaining cap, so a long scan never starts on a near-dead session.
_REFRESH_MARGIN = timedelta(minutes=10)
# Never request longer than the role-chaining ceiling (1h): AWS rejects a longer
# duration when the base identity is itself an assumed role.
_MAX_DURATION_SECONDS = 3600


class StsCredentialsAdapter(AwsRoleCredentialsPort):
    """boto3 STS assume-role with an in-process, thread-safe per-role cache."""

    def __init__(self) -> None:
        self._cache: dict[str, dict] = {}
        self._lock = threading.Lock()

    def assume_role(
        self,
        *,
        account_id: str,
        role_name: str,
        external_id: str,
        session_name: str = "autosec",
        duration_seconds: int = 3600,
        use_cache: bool = True,
    ) -> dict:
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

        if use_cache:
            cached = self._cached_credentials(role_arn)
            if cached is not None:
                logger.debug("aws_role_session_cache_hit account=%s role=%s", account_id, role_name)
                return cached

        import boto3

        creds = boto3.client("sts").assume_role(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            ExternalId=external_id,
            DurationSeconds=min(duration_seconds, _MAX_DURATION_SECONDS),
        )["Credentials"]
        logger.info("aws_role_assumed account=%s role=%s cached=%s", account_id, role_name, use_cache)

        if use_cache:
            with self._lock:
                self._cache[role_arn] = creds
        return creds

    def _cached_credentials(self, role_arn: str) -> dict | None:
        with self._lock:
            creds = self._cache.get(role_arn)
        if creds is None:
            return None
        expiry = creds.get("Expiration")
        if isinstance(expiry, datetime) and expiry - datetime.now(timezone.utc) > _REFRESH_MARGIN:
            return creds
        # Missing/expiring expiry — evict so the caller re-assumes a fresh session.
        with self._lock:
            self._cache.pop(role_arn, None)
        return None
