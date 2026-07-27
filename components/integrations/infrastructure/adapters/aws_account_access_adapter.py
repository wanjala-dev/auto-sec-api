"""Resolve a workspace's AWS connection and vend credentials for an account.

Reads integrations' OWN ``AwsOrganizationConnection`` (own-context infra access
is allowed here) to find the ``role_name`` + ``external_id`` for the account,
then delegates to the shared credential-vending port. This is the one place that
knows "connection → assume-role parameters"; other contexts consume the port.
"""

from __future__ import annotations

import logging

from components.integrations.application.ports.aws_account_access_port import (
    AwsAccountAccessPort,
)
from components.integrations.application.providers.aws_credentials_provider import (
    get_aws_credentials_port,
)

logger = logging.getLogger(__name__)


class AwsAccountAccessAdapter(AwsAccountAccessPort):
    def credentials_for(
        self,
        *,
        workspace_id: str,
        account_id: str,
        session_name: str = "autosec",
        use_cache: bool = True,
    ) -> dict:
        from infrastructure.persistence.integrations.models import (
            AwsAccountLink,
            AwsOrganizationConnection,
        )

        # Prefer a connection that actually links this account; fall back to the
        # workspace's connected org (management/single account case).
        connection = (
            AwsOrganizationConnection.objects.filter(
                workspace_id=workspace_id,
                accounts__account_id=account_id,
            )
            .distinct()
            .first()
        )
        if connection is None:
            connection = AwsOrganizationConnection.objects.filter(
                workspace_id=workspace_id,
                status=AwsOrganizationConnection.Status.CONNECTED,
            ).first()
        if connection is None:
            raise LookupError(f"no AWS connection for workspace={workspace_id} covering account={account_id}")

        creds = get_aws_credentials_port().assume_role(
            account_id=account_id,
            role_name=connection.role_name,
            external_id=connection.external_id,
            session_name=session_name,
            use_cache=use_cache,
        )
        # Best-effort: the successful assume proves the role in this account.
        AwsAccountLink.objects.filter(connection_id=connection.id, account_id=account_id).update(
            status=AwsAccountLink.Status.VERIFIED
        )
        logger.info(
            "aws_account_access_resolved workspace=%s account=%s connection=%s",
            workspace_id,
            account_id,
            connection.id,
        )
        return creds
