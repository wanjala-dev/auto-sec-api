"""ORM adapter: revoke a workspace membership + record the side effects.

Implements :class:`WorkspaceMemberRemovalPort`. Sole owner of the
``WorkspaceMembership`` revocation write.

Revocation is a SOFT status flip to ``Status.SUSPENDED`` — the existing
membership status machine's revoked state, which
``workspace_relationship_repository`` already reactivates on re-join. No row is
deleted, so re-inviting the person restores their history.

Side effects, both through the sanctioned funnels:
- audit: the audit context's application provider (``log_field_change``) — an
  immutable record of who revoked whom, when, and why;
- notification: the notifications context's application provider (``dispatch``)
  — the ONLY sanctioned way
  to create Notification rows from another context (enforced by
  ``tests/architecture/test_notification_dispatch_rules.py``).

Both are best-effort AFTER the state change: a notification outage must not
leave a member half-removed. Failures are logged with a traceback, never
swallowed silently.
"""

from __future__ import annotations

import logging

from components.membership.application.ports.workspace_member_removal_port import (
    RemoveWorkspaceMemberCommand,
    RemoveWorkspaceMemberResult,
    WorkspaceMemberRemovalPort,
)

logger = logging.getLogger(__name__)


class OrmWorkspaceMemberRemovalRepository(WorkspaceMemberRemovalPort):
    def find_membership_role(self, *, workspace_id: str, user_id: str) -> str | None:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        return (
            WorkspaceMembership.objects.filter(workspace_id=workspace_id, user_id=user_id)
            .values_list("role", flat=True)
            .first()
        )

    def is_workspace_owner(self, *, workspace_id: str, user_id: str) -> bool:
        from infrastructure.persistence.workspaces.models import Workspace

        owner_id = (
            Workspace.objects.all_objects().filter(pk=workspace_id).values_list("workspace_owner_id", flat=True).first()
        )
        return bool(owner_id) and str(owner_id) == str(user_id)

    def revoke(self, *, command: RemoveWorkspaceMemberCommand) -> RemoveWorkspaceMemberResult:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        membership = (
            WorkspaceMembership.objects.filter(workspace_id=command.workspace_id, user_id=command.target_user_id)
            .select_related("workspace", "user")
            .first()
        )
        if membership is None:  # deleted between the use case's check and now
            return RemoveWorkspaceMemberResult(
                workspace_id=command.workspace_id,
                target_user_id=command.target_user_id,
                removed=False,
            )

        previous_status = membership.status
        if previous_status == WorkspaceMembership.Status.SUSPENDED:
            # Idempotent: already revoked — no duplicate audit row, no re-notify.
            return RemoveWorkspaceMemberResult(
                workspace_id=command.workspace_id,
                target_user_id=command.target_user_id,
                removed=False,
                already_revoked=True,
            )

        membership.status = WorkspaceMembership.Status.SUSPENDED
        membership.save(update_fields=["status"])

        self._audit(membership=membership, previous_status=previous_status, command=command)
        self._notify(membership=membership, command=command)

        return RemoveWorkspaceMemberResult(
            workspace_id=command.workspace_id,
            target_user_id=command.target_user_id,
            removed=True,
        )

    @staticmethod
    def _audit(*, membership, previous_status: str, command: RemoveWorkspaceMemberCommand) -> None:
        """Immutable record of the revocation, through the audit provider."""
        from components.audit.application.providers.audit_log_provider import get_audit_log_provider
        from infrastructure.persistence.users.models import CustomUser
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        actor = CustomUser.objects.filter(id=command.performed_by).first()
        try:
            get_audit_log_provider().log_field_change(
                instance=membership,
                field_name="status",
                previous_value=previous_status,
                new_value=WorkspaceMembership.Status.SUSPENDED,
                actor=actor,
                reason=command.reason
                or ("left the workspace" if command.is_self_removal else "removed from the workspace"),
            )
        except Exception:
            logger.exception(
                "workspace_member_removal audit failed workspace_id=%s target_user_id=%s",
                command.workspace_id,
                command.target_user_id,
            )

    @staticmethod
    def _notify(*, membership, command: RemoveWorkspaceMemberCommand) -> None:
        """Tell the removed user, through the canonical dispatch funnel.

        Skipped for a self-removal — nobody needs a notification that they
        themselves clicked "leave".
        """
        if command.is_self_removal:
            return

        from components.notifications.application.providers.notification_factory_provider import (
            get_notification_factory_provider,
        )
        from infrastructure.persistence.users.models import CustomUser

        actor = CustomUser.objects.filter(id=command.performed_by).first()
        if actor is None:
            return
        workspace_name = getattr(membership.workspace, "workspace_name", "") or "the workspace"
        try:
            get_notification_factory_provider().dispatch(
                actor=actor,
                workspace=membership.workspace,
                verb=f"removed you from {workspace_name}",
                notification_type="system",
                recipients=[membership.user],
                metadata={
                    "event": "workspace_member_removed",
                    "workspace_id": str(command.workspace_id),
                    "removed_by": str(command.performed_by),
                },
            )
        except Exception:
            logger.exception(
                "workspace_member_removal notification failed workspace_id=%s target_user_id=%s",
                command.workspace_id,
                command.target_user_id,
            )
