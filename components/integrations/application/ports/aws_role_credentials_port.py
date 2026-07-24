"""Port: vend short-lived AWS credentials by assuming a customer's audit role.

The single credential-vending seam for AWS access across the platform — the
"token vending machine" AWS's SaaS reference architecture prescribes so that
individual features never re-implement assume-role. Onboarding verification,
the CDR log-ingest pipeline, and the CSPM scanner all obtain credentials
through this one port.

The platform's own identity (workload identity — EC2 instance profile / ECS
task role / EKS IRSA, resolved by boto3's default chain) is the base principal;
the adapter assumes the per-account read-only role with the vendor-generated
ExternalId (confused-deputy defense) and returns ephemeral STS credentials.
Customer keys are never stored — role assumption only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class AwsRoleCredentialsPort(ABC):
    """Assume a customer audit role and return ephemeral STS credentials."""

    @abstractmethod
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
        """Return ``{AccessKeyId, SecretAccessKey, SessionToken, Expiration}``.

        ``use_cache`` serves a live-verification dry-run (``False``) vs a
        scan/ingest read that reuses a warm per-role session (``True``). Raises
        on assume-role failure — the caller records the error state.
        """
        raise NotImplementedError
