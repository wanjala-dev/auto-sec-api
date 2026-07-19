"""Port: verify a customer's AWS audit role and discover member accounts.

The application core needs exactly one capability from the cloud side of
onboarding: "assume the customer's audit role (dry-run) and, org-wide, list
the member accounts". The boto3/STS mechanics live in the
``StsOrgAdapter`` secondary adapter; this port keeps the connection
service free of any AWS SDK knowledge.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class OrgVerificationPort(ABC):
    """Assume-role verification + AWS Organizations discovery."""

    @abstractmethod
    def verify_and_discover(
        self,
        *,
        management_account_id: str,
        role_name: str,
        external_id: str,
        discover: bool = True,
    ) -> dict:
        """Dry-run assume the audit role; optionally walk the organization.

        Returns ``{"organization_id": str, "accounts": [{"id", "name"}, ...]}``.
        Raises on assume-role failure — the caller records the error state.
        """
        raise NotImplementedError
