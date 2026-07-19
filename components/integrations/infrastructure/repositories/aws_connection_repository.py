"""Repository for AWS organization connections (the ONLY ORM slot).

Every ``AwsOrganizationConnection`` / ``AwsAccountLink`` read/write the
integrations context performs goes through here — controllers and the
application service never touch ``infrastructure.persistence`` directly
(architecture rule: controllers depend on providers/services, services
depend on repositories/ports).
"""

from __future__ import annotations

import logging

from django.utils import timezone

from infrastructure.persistence.integrations.models import (
    AwsAccountLink,
    AwsOrganizationConnection,
)

logger = logging.getLogger(__name__)


class AwsConnectionRepository:
    """ORM access for AWS onboarding connections, workspace-scoped."""

    def list_for_workspace(self, workspace_id) -> list[AwsOrganizationConnection]:
        return list(AwsOrganizationConnection.objects.filter(workspace_id=workspace_id).prefetch_related("accounts"))

    def get(self, workspace_id, connection_id) -> AwsOrganizationConnection | None:
        return AwsOrganizationConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()

    def get_or_create(
        self,
        *,
        workspace_id,
        management_account_id: str,
        defaults: dict,
        created_by,
    ) -> tuple[AwsOrganizationConnection, bool]:
        return AwsOrganizationConnection.objects.get_or_create(
            workspace_id=workspace_id,
            management_account_id=management_account_id,
            defaults={**defaults, "created_by": created_by},
        )

    def mark_error(self, conn: AwsOrganizationConnection, message: str) -> None:
        conn.status = AwsOrganizationConnection.Status.ERROR
        conn.last_error = message[:2000]
        conn.save(update_fields=["status", "last_error", "updated_at"])

    def mark_connected(
        self,
        conn: AwsOrganizationConnection,
        *,
        organization_id: str,
        accounts: list[dict],
    ) -> AwsOrganizationConnection:
        conn.status = AwsOrganizationConnection.Status.CONNECTED
        conn.organization_id = organization_id or conn.organization_id
        conn.last_verified_at = timezone.now()
        conn.last_error = ""
        conn.save()
        for acct in accounts or []:
            AwsAccountLink.objects.update_or_create(
                connection=conn,
                account_id=acct["id"],
                defaults={
                    "account_name": acct.get("name") or "",
                    "status": AwsAccountLink.Status.DISCOVERED,
                },
            )
        return conn
