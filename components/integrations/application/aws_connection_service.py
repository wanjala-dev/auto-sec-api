"""Application service for AWS organization onboarding.

Orchestrates the connection lifecycle (create → template → verify) against
the repository and the ``OrgVerificationPort``. Controllers call this via
``get_aws_connection_service()`` (the provider/composition root) and never
touch the ORM or the STS adapter directly.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any

from components.integrations.application.ports.org_verification_port import (
    OrgVerificationPort,
)

logger = logging.getLogger(__name__)


class OrgVerificationError(Exception):
    """Assume-role verification failed; the connection was marked ERROR."""


@dataclass
class AwsConnectionService:
    """Use cases for the AWS onboarding connection lifecycle."""

    _repo: Any
    _verifier: OrgVerificationPort

    # ── Reads ────────────────────────────────────────────────────────────

    def list_connections(self, workspace_id):
        return self._repo.list_for_workspace(workspace_id)

    def get_connection(self, workspace_id, connection_id):
        return self._repo.get(workspace_id, connection_id)

    # ── Create ───────────────────────────────────────────────────────────

    def create_connection(
        self,
        *,
        workspace_id,
        created_by,
        name: str,
        role_name: str,
        management_account_id: str,
        org_wide: bool,
        regions: list,
        trail_s3_bucket: str,
        sqs_queue_url: str,
    ):
        """Create (or return) the workspace's connection for a management account.

        Generates the vendor-side ``external_id`` (confused-deputy token per
        AWS SEC03-BP09) — never customer-chosen.
        """
        return self._repo.get_or_create(
            workspace_id=workspace_id,
            management_account_id=management_account_id,
            created_by=created_by,
            defaults={
                "name": name or "AWS Organization",
                "role_name": role_name or "AutoSecAuditRole",
                "org_wide": org_wide,
                "regions": regions or [],
                "trail_s3_bucket": trail_s3_bucket or "",
                "sqs_queue_url": sqs_queue_url or "",
                # Vendor-generated, URL-safe, unique — the confused-deputy token.
                "external_id": f"autosec-{secrets.token_urlsafe(24)}",
            },
        )

    # ── Verify ───────────────────────────────────────────────────────────

    def verify_connection(self, conn):
        """Dry-run assume the audit role; on success discover member accounts.

        On failure the connection is marked ERROR (with the message recorded)
        and ``OrgVerificationError`` is raised for the adapter to translate
        into a 502. On success the connection flips to CONNECTED and every
        discovered account is upserted as an ``AwsAccountLink``.
        """
        try:
            result = self._verifier.verify_and_discover(
                management_account_id=conn.management_account_id,
                role_name=conn.role_name,
                external_id=conn.external_id,
                discover=conn.org_wide,
            )
        except Exception as exc:
            logger.exception(
                "aws_connection_verify_failed connection_id=%s workspace_id=%s",
                conn.id,
                conn.workspace_id,
            )
            message = str(exc)[:2000]
            self._repo.mark_error(conn, message)
            raise OrgVerificationError(message) from exc

        return self._repo.mark_connected(
            conn,
            organization_id=result.get("organization_id") or "",
            accounts=result.get("accounts") or [],
        )
