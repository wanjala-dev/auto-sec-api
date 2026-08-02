"""Adapter: write the invited user's membership + group rows against the ORM.

Implements :class:`InviteMembershipStorePort`. This is the ONLY place the invite
accept flow touches ``WorkspaceMembership`` / ``WorkspaceRole`` /
``WorkspaceGroup*`` — the writes moved here verbatim from the team accept use
case, so the behaviour is byte-identical; only their home changed to the context
that owns the models.

Opens no transaction of its own — runs inside the caller's ``atomic()`` so a
later failure in the invite flow rolls these writes back too.
"""

from __future__ import annotations

from components.workspace.application.commands.invite_membership_write import (
    ExistingMembershipProbe,
    WriteInviteMembershipCommand,
)
from components.workspace.application.ports.invite_membership_store_port import (
    InviteMembershipStorePort,
)


class OrmInviteMembershipRepository(InviteMembershipStorePort):
    def probe_existing_membership(self, *, workspace_id: str, user_id: str) -> ExistingMembershipProbe:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        existing_membership = WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            user_id=user_id,
        ).first()
        active = bool(existing_membership and existing_membership.status == WorkspaceMembership.Status.ACTIVE)
        return ExistingMembershipProbe(exists=existing_membership is not None, active=active)

    def write_membership(self, *, command: WriteInviteMembershipCommand) -> None:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceGroup,
            WorkspaceGroupMembership,
            WorkspaceMembership,
            WorkspaceRole,
        )

        if command.preserving_existing_membership:
            # Preserve role/persona/workspace_role/invited_by; only refresh
            # accepted_at so audit trails stay accurate.
            existing_membership = WorkspaceMembership.objects.filter(
                workspace_id=command.workspace_id,
                user_id=command.user_id,
            ).first()
            if existing_membership is not None:
                existing_membership.accepted_at = command.accepted_at
                existing_membership.save(update_fields=["accepted_at"])
        else:
            # Double-write the workspace_role FK so RBAC readers can migrate to
            # the FK once Phase 2 lands. System-role lookup is scoped to the
            # seeded templates.
            system_role = WorkspaceRole.objects.filter(
                workspace__isnull=True,
                is_system=True,
                slug=command.role,
            ).first()
            WorkspaceMembership.objects.update_or_create(
                workspace_id=command.workspace_id,
                user_id=command.user_id,
                defaults={
                    "persona": command.persona,
                    "role": command.role,
                    "workspace_role": system_role,
                    "status": WorkspaceMembership.Status.ACTIVE,
                    "invited_by_id": command.invited_by_id,
                    "accepted_at": command.accepted_at,
                },
            )

        # Enroll the user into any permission groups the inviter selected.
        # WorkspaceGroupMembership has a unique_together constraint so we use
        # get_or_create to stay idempotent.
        permission_group_ids = list(command.permission_group_ids or [])
        if permission_group_ids:
            groups = WorkspaceGroup.objects.filter(
                workspace_id=command.workspace_id,
                id__in=permission_group_ids,
            )
            for group in groups:
                WorkspaceGroupMembership.objects.get_or_create(
                    group=group,
                    user_id=command.user_id,
                    defaults={"added_by_id": command.invited_by_id},
                )
