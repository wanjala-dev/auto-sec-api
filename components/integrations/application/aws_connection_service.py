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

from components.integrations.application.ports.connection_scan_dispatch_port import (
    ConnectionScanDispatchPort,
)
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
    _scan_dispatcher: ConnectionScanDispatchPort | None = None

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

        Defaults are WORKSPACE-derived (aws_role_naming): the artifacts live in
        the customer's account and should read as theirs — ``FauraAuditRole``,
        not a vendor-branded name (Henry, 2026-08-18).
        """
        from components.integrations.domain.aws_role_naming import (
            default_audit_role_name,
            external_id_prefix,
        )

        ws_name = self._repo.workspace_name(workspace_id)
        return self._repo.get_or_create(
            workspace_id=workspace_id,
            management_account_id=management_account_id,
            created_by=created_by,
            defaults={
                "name": name or "AWS Organization",
                "role_name": role_name or default_audit_role_name(ws_name),
                "org_wide": org_wide,
                "regions": regions or [],
                "trail_s3_bucket": trail_s3_bucket or "",
                "sqs_queue_url": sqs_queue_url or "",
                # Vendor-generated, URL-safe, unique — the confused-deputy token.
                "external_id": f"{external_id_prefix(ws_name)}-{secrets.token_urlsafe(24)}",
            },
        )

    # ── Verify ───────────────────────────────────────────────────────────

    def verify_connection(self, conn):
        """Dry-run assume the audit role; on success discover member accounts.

        On failure the connection is marked ERROR (with the message recorded)
        and ``OrgVerificationError`` is raised for the adapter to translate
        into a 502. On success the connection flips to CONNECTED, the discovered
        accounts are reconciled into ``AwsAccountLink`` rows, and the first scan
        is dispatched automatically — see :meth:`verify_and_scan`.
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
            org_walked=bool(result.get("org_walked")),
        )

    def verify_and_scan(self, conn) -> tuple[Any, dict | None]:
        """Verify, then kick the first scan — the whole point of connecting.

        Verification alone used to leave the account silent: the wizard's last
        step was a manual "Scan" button, so an operator who connected and closed
        the tab saw an empty product until the 02:00 beat. No error, no signal —
        the same silent class as the discovery gap. Connecting a source now
        starts scanning it.

        Returns ``(connection, scans)``. ``scans`` is ``None`` when there is
        nothing scannable yet (a legitimate state: verified, no accounts
        discovered — say so rather than reporting a hollow zero). A dispatch
        problem never fails the verification; the connection is verified either
        way and the scheduled sweep is the retry path.
        """
        conn = self.verify_connection(conn)
        if self._scan_dispatcher is None:
            return conn, None

        outcome = self._scan_dispatcher.dispatch_after_commit(
            workspace_id=str(conn.workspace_id),
            connection_id=str(conn.id),
        )
        # Only an unsettled result may be trusted as "not yet known"; a settled
        # result with nothing scannable is a real, reportable state.
        if outcome.get("settled") and not outcome.get("scannable"):
            return conn, None
        return conn, outcome

    # ── Scheduled re-discovery ───────────────────────────────────────────

    def rediscover_accounts(self, conn) -> dict:
        """Re-walk ONE organization and reconcile its account links.

        Reuses the same ``verify_and_discover`` seam as the operator verify —
        there is no second ``ListAccounts`` path, and there should not be: you
        cannot list an organization without assuming the role first, so the
        coupling the port's name implies is inherent to the AWS API, not an
        accident of ours. What differs is only what we do with the result:
        ``clear_failed=False`` (a background read does not get to overrule a
        health verdict) and no status/error write (a transient Organizations
        blip must not flip a working connection to ERROR in the operator's HUD).
        """
        result = self._verifier.verify_and_discover(
            management_account_id=conn.management_account_id,
            role_name=conn.role_name,
            external_id=conn.external_id,
            discover=True,
        )
        return self._repo.record_rediscovery(
            conn,
            accounts=result.get("accounts") or [],
            org_walked=bool(result.get("org_walked")),
        )

    def rediscover_all_connections(self) -> dict:
        """Sweep every CONNECTED org-wide connection in this database.

        ONE customer's broken org must never stop everyone else's re-discovery,
        so each connection is contained: log the exception with its identifiers,
        count it, keep going. The return is the operator-facing summary.
        """
        totals = {
            "connections": 0,
            "failed": 0,
            "created": 0,
            "reactivated": 0,
            "suspended": 0,
            "protected": 0,
        }

        for conn in self._repo.list_connected_org_wide():
            totals["connections"] += 1
            try:
                counts = self.rediscover_accounts(conn)
            except Exception:
                totals["failed"] += 1
                logger.exception(
                    "aws_rediscovery_failed connection_id=%s workspace_id=%s management_account=%s",
                    conn.id,
                    conn.workspace_id,
                    conn.management_account_id,
                )
                continue
            for key in ("created", "reactivated", "suspended", "protected"):
                totals[key] += counts.get(key, 0)

        return totals
