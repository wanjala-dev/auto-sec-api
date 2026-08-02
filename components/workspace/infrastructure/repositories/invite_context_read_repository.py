"""Adapter: workspace-side invite-context reads against the ORM.

Implements :class:`InviteContextReadPort`. The reads moved here verbatim from the
team create-invite use case (workspace existence + owner, owner/admin RBAC check,
team resolution, permission-group ownership validation), so behaviour is
unchanged; only their home changed to the context that owns the models.
"""

from __future__ import annotations

from components.workspace.application.ports.invite_context_read_port import (
    InviteContextReadPort,
    InviteContextResult,
)


class OrmInviteContextReadRepository(InviteContextReadPort):
    def get_user_email(self, *, user_id: str) -> str | None:
        from infrastructure.persistence.users.models import CustomUser

        user = CustomUser.objects.filter(id=user_id).first()
        if user is None:
            return None
        return (getattr(user, "email", "") or "").strip().lower()

    def resolve(
        self,
        *,
        workspace_id: str,
        inviter_user_id: str | None,
        inviter_is_staff: bool,
        inviter_is_superuser: bool,
        team_required: bool,
        team_id: str | None,
        permission_group_ids: list[str] | None,
    ) -> InviteContextResult:
        from infrastructure.persistence.team.models import Team
        from infrastructure.persistence.workspaces.models import (
            Workspace,
            WorkspaceGroup,
            WorkspaceMembership,
        )

        workspace = Workspace.objects.filter(id=workspace_id).first()
        if workspace is None:
            return InviteContextResult(
                workspace_found=False,
                authorized=False,
                team_found=True,
                validated_group_ids=[],
            )

        # Permission check — RBAC role only. Owner or admin (or staff/superuser).
        is_authorized = inviter_is_staff or inviter_is_superuser
        if not is_authorized:
            if str(workspace.workspace_owner_id) == str(inviter_user_id):
                is_authorized = True
            else:
                is_authorized = WorkspaceMembership.objects.filter(
                    workspace_id=workspace.id,
                    user_id=inviter_user_id,
                    status=WorkspaceMembership.Status.ACTIVE,
                    role__in=(
                        WorkspaceMembership.Role.OWNER,
                        WorkspaceMembership.Role.ADMIN,
                    ),
                ).exists()
        if not is_authorized:
            return InviteContextResult(
                workspace_found=True,
                authorized=False,
                team_found=True,
                validated_group_ids=[],
            )

        team_found = True
        if team_required:
            team = Team.objects.filter(id=team_id, workspace=workspace).first()
            team_found = team is not None

        # Validate permission-group ownership before parking them on the
        # invitation row — an inviter could otherwise attach groups from another
        # workspace they happen to know the ids of.
        validated_group_ids: list[str] = []
        if permission_group_ids:
            valid_ids = set(
                str(gid)
                for gid in WorkspaceGroup.objects.filter(
                    workspace_id=workspace.id,
                    id__in=[str(gid) for gid in permission_group_ids],
                ).values_list("id", flat=True)
            )
            validated_group_ids = [str(gid) for gid in permission_group_ids if str(gid) in valid_ids]

        return InviteContextResult(
            workspace_found=True,
            authorized=True,
            team_found=team_found,
            validated_group_ids=validated_group_ids,
        )
