"""Port: resolve ready-to-use AWS credentials for a workspace's account.

``AwsRoleCredentialsPort`` vends creds but the caller must first know the
account's ``role_name`` + ``external_id`` — which live on the workspace's
``AwsOrganizationConnection`` (integrations' own ORM). Every consumer that wants
"creds for account X in workspace W" would otherwise reach into integrations'
persistence directly (the cross-context infra import the architecture skill
calls debt #3). This port closes that seam: integrations resolves the connection
*inside* its own boundary and hands back credentials, so other contexts depend
only on ``integrations.application`` — never its models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AwsAccountRef:
    """A scannable account + its target regions (from the workspace's connection).

    ``regions`` empty means the connection didn't pin a set — the caller picks a
    sensible default. Keeps callers off the ``AwsOrganizationConnection`` ORM."""

    account_id: str
    regions: tuple[str, ...] = ()


class AwsAccountAccessPort(ABC):
    @abstractmethod
    def credentials_for(
        self,
        *,
        workspace_id: str,
        account_id: str,
        session_name: str = "autosec",
        use_cache: bool = True,
    ) -> dict:
        """Return ``{AccessKeyId, SecretAccessKey, SessionToken, ...}`` for the
        account, assuming the audit role recorded on the workspace's connection.

        Raises ``LookupError`` if the workspace has no connection covering the
        account, and propagates assume-role failures from the credentials port.
        """

    @abstractmethod
    def accounts_for(self, workspace_id: str) -> list[AwsAccountRef]:
        """Every scannable AWS account for the workspace + its target regions,
        resolved from the workspace's CONNECTED connection. Empty list if the
        workspace has no connection. Terminal account links (failed/suspended/
        excluded) are skipped, mirroring the scanner fan-out."""
