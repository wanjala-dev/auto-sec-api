"""Repository for AWS organization connections (the ONLY ORM slot).

Every ``AwsOrganizationConnection`` / ``AwsAccountLink`` read/write the
integrations context performs goes through here — controllers and the
application service never touch ``infrastructure.persistence`` directly
(architecture rule: controllers depend on providers/services, services
depend on repositories/ports).
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from infrastructure.persistence.integrations.models import (
    AwsAccountLink,
    AwsOrganizationConnection,
)

logger = logging.getLogger(__name__)


class AwsConnectionRepository:
    """ORM access for AWS onboarding connections, workspace-scoped."""

    def workspace_name(self, workspace_id) -> str:
        """Display name of the workspace, "" when it doesn't exist — feeds the
        workspace-derived default role naming (aws_role_naming)."""
        from infrastructure.persistence.workspaces.models import Workspace

        row = Workspace.objects.all_objects().filter(id=workspace_id).values_list("workspace_name", flat=True).first()
        return str(row or "")

    def list_for_workspace(self, workspace_id) -> list[AwsOrganizationConnection]:
        return list(AwsOrganizationConnection.objects.filter(workspace_id=workspace_id).prefetch_related("accounts"))

    def get(self, workspace_id, connection_id) -> AwsOrganizationConnection | None:
        return AwsOrganizationConnection.objects.filter(id=connection_id, workspace_id=workspace_id).first()

    def latest_connected_for_workspace(self, workspace_id) -> AwsOrganizationConnection | None:
        """The workspace's most recent *connected* AWS source — the one the log
        readers (error scan + temporal aggregator) ingest from. Returns ``None``
        when the workspace has no connected integration."""
        return (
            AwsOrganizationConnection.objects.filter(
                workspace_id=workspace_id,
                status=AwsOrganizationConnection.Status.CONNECTED,
            )
            .order_by("-created_at")
            .first()
        )

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

    def list_connected_org_wide(self) -> list[AwsOrganizationConnection]:
        """Connections the scheduled re-discovery sweep is allowed to walk.

        Deliberately narrow. A connection that is not CONNECTED has no proven
        role to assume, and a non-``org_wide`` one has no organization to list —
        calling either every hour would burn STS/Organizations calls to learn
        nothing. ``only()`` keeps the sweep's read to the columns the verifier
        and the reconciler actually use.
        """
        return list(
            AwsOrganizationConnection.objects.filter(
                status=AwsOrganizationConnection.Status.CONNECTED,
                org_wide=True,
            ).only("id", "workspace", "management_account_id", "role_name", "external_id")
        )

    def reconcile_accounts(
        self,
        conn: AwsOrganizationConnection,
        *,
        accounts: list[dict],
        org_walked: bool,
        clear_failed: bool,
    ) -> dict:
        """Fold a discovery result into this connection's ``AwsAccountLink`` rows.

        The ONE account-link write path — manual verify and the scheduled sweep
        both land here, so the two can never drift (they did: verify used to
        blanket-upsert every discovered account to DISCOVERED, which silently
        destroyed an operator's EXCLUDED intent on every re-verify).

        Rules, by existing status:

        ===========  ==============================  ==========================
        link         seen ACTIVE in the org          absent from the ACTIVE set
        ===========  ==============================  ==========================
        (none)       create DISCOVERED               —
        DISCOVERED   DISCOVERED                      SUSPENDED
        VERIFIED     VERIFIED (untouched)            SUSPENDED
        SUSPENDED    DISCOVERED (it came back)       SUSPENDED
        FAILED       FAILED, unless ``clear_failed``  SUSPENDED
        EXCLUDED     EXCLUDED — always               EXCLUDED — always
        ===========  ==============================  ==========================

        Two rules carry the weight:

        * **EXCLUDED is operator intent and is never clobbered.** Discovery
          reports what AWS says; it does not get to overrule what a human
          decided. Only an operator can un-exclude an account.
        * **FAILED is a verdict about OUR role access, and discovery cannot
          re-test it** — listing an account proves org membership, not that the
          role assumes. Clearing it automatically would flap the link
          FAILED → DISCOVERED → scan → FAILED on every sweep. ``clear_failed``
          is passed only by the operator-initiated verify, which IS a deliberate
          "re-test my access" action.

        Nothing is ever deleted: a departed account keeps its row (and its scan
        history) as SUSPENDED. ``org_walked=False`` means the ``accounts`` list
        is not authoritative, so the absence sweep is skipped entirely.
        """
        seen = {a["id"]: (a.get("name") or "") for a in accounts or []}
        counts = {"created": 0, "reactivated": 0, "suspended": 0, "unchanged": 0, "protected": 0}

        # A partial reconcile is worse than none — an operator would see half an
        # org suspended with no way to tell which half is real.
        with transaction.atomic():
            existing = {
                link.account_id: link for link in AwsAccountLink.objects.select_for_update().filter(connection=conn)
            }

            for account_id, name in seen.items():
                link = existing.get(account_id)
                if link is None:
                    AwsAccountLink.objects.create(
                        connection=conn,
                        account_id=account_id,
                        account_name=name,
                        status=AwsAccountLink.Status.DISCOVERED,
                    )
                    counts["created"] += 1
                    continue

                next_status = self._status_for_seen_account(link.status, clear_failed=clear_failed)
                if link.status == AwsAccountLink.Status.EXCLUDED:
                    counts["protected"] += 1
                elif next_status != link.status:
                    counts["reactivated"] += 1
                else:
                    counts["unchanged"] += 1

                # The name is refreshed regardless — it is a label, not a state.
                link.account_name = name or link.account_name
                link.status = next_status
                link.save(update_fields=["account_name", "status", "updated_at"])

            if org_walked:
                counts["suspended"] = self._suspend_departed(existing, seen_ids=set(seen))

        logger.info(
            "aws_accounts_reconciled connection_id=%s workspace_id=%s org_walked=%s "
            "created=%d reactivated=%d suspended=%d protected=%d unchanged=%d",
            conn.id,
            conn.workspace_id,
            org_walked,
            counts["created"],
            counts["reactivated"],
            counts["suspended"],
            counts["protected"],
            counts["unchanged"],
        )
        return counts

    @staticmethod
    def _status_for_seen_account(current: str, *, clear_failed: bool) -> str:
        if current == AwsAccountLink.Status.EXCLUDED:
            return current  # operator intent — never overruled by discovery
        if current == AwsAccountLink.Status.FAILED and not clear_failed:
            return current  # a health verdict discovery is not entitled to clear
        if current == AwsAccountLink.Status.VERIFIED:
            return current  # already proven; don't demote a working account
        return AwsAccountLink.Status.DISCOVERED

    @staticmethod
    def _suspend_departed(existing: dict, *, seen_ids: set) -> int:
        """Mark rows the authoritative walk did not return as SUSPENDED.

        Never deletes — history and provenance matter, and a suspended account
        that rejoins the org is reactivated by the next sweep. EXCLUDED rows are
        left alone here too: an operator's exclusion outlives the account's
        membership, and both statuses are terminal for the scan fan-out anyway.
        """
        departed = [
            link.pk
            for account_id, link in existing.items()
            if account_id not in seen_ids
            and link.status not in (AwsAccountLink.Status.SUSPENDED, AwsAccountLink.Status.EXCLUDED)
        ]
        if not departed:
            return 0
        return AwsAccountLink.objects.filter(pk__in=departed).update(
            status=AwsAccountLink.Status.SUSPENDED,
            updated_at=timezone.now(),
        )

    def mark_connected(
        self,
        conn: AwsOrganizationConnection,
        *,
        organization_id: str,
        accounts: list[dict],
        org_walked: bool = False,
    ) -> AwsOrganizationConnection:
        """Operator-initiated verify succeeded: flip to CONNECTED and reconcile.

        ``clear_failed=True`` because a human pressing Verify is explicitly
        asking us to re-test access — that is the sanctioned recovery path out
        of FAILED. It still does NOT clear EXCLUDED (that is intent, not health).
        """
        conn.status = AwsOrganizationConnection.Status.CONNECTED
        conn.organization_id = organization_id or conn.organization_id
        conn.last_verified_at = timezone.now()
        conn.last_error = ""
        conn.save()
        self.reconcile_accounts(
            conn,
            accounts=accounts,
            org_walked=org_walked,
            clear_failed=True,
        )
        return conn

    def record_rediscovery(self, conn: AwsOrganizationConnection, *, accounts: list[dict], org_walked: bool) -> dict:
        """Scheduled sweep succeeded: reconcile only, and stamp ``last_verified_at``.

        Deliberately does NOT touch ``status``/``last_error``. A background sweep
        is a read of the customer's org; it must not narrate the connection's
        health in the operator's HUD, in either direction.
        """
        counts = self.reconcile_accounts(
            conn,
            accounts=accounts,
            org_walked=org_walked,
            clear_failed=False,
        )
        conn.last_verified_at = timezone.now()
        conn.save(update_fields=["last_verified_at", "updated_at"])
        return counts
