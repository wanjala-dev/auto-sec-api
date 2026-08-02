"""Adapter: write the invited user's membership via ``workspace``'s surface.

Implements the team-owned :class:`WorkspaceMembershipWritePort` by delegating to
``workspace``'s ``WriteInviteMembershipUseCase`` (built by
``InviteMembershipProvider``) — a permitted cross-context call into another
context's application layer, never its persistence. ``workspace`` owns the
``WorkspaceMembership``/``WorkspaceRole``/``WorkspaceGroup*`` write; the team
context only asks for it (architecture-manifesto Rule 2 / architecture-skill C2).
"""

from __future__ import annotations

from datetime import datetime

from components.team.application.ports.workspace_membership_write_port import (
    MembershipProbe,
    WorkspaceMembershipWritePort,
)


class WorkspaceMembershipWriteAdapter(WorkspaceMembershipWritePort):
    def probe_membership(self, *, workspace_id: str, user_id: str) -> MembershipProbe:
        from components.workspace.application.providers.invite_membership_provider import (
            get_invite_membership_provider,
        )

        use_case = get_invite_membership_provider().build_use_case()
        probe = use_case.probe_existing_membership(workspace_id=workspace_id, user_id=user_id)
        return MembershipProbe(exists=probe.exists, active=probe.active)

    def write_membership(
        self,
        *,
        workspace_id: str,
        user_id: str,
        persona: str,
        role: str,
        invited_by_id: str | None,
        accepted_at: datetime,
        preserving_existing_membership: bool,
        permission_group_ids: list[str] | None = None,
    ) -> None:
        from components.workspace.application.commands.invite_membership_write import (
            WriteInviteMembershipCommand,
        )
        from components.workspace.application.providers.invite_membership_provider import (
            get_invite_membership_provider,
        )

        use_case = get_invite_membership_provider().build_use_case()
        use_case.execute(
            command=WriteInviteMembershipCommand(
                workspace_id=workspace_id,
                user_id=user_id,
                persona=persona,
                role=role,
                invited_by_id=invited_by_id,
                accepted_at=accepted_at,
                preserving_existing_membership=preserving_existing_membership,
                permission_group_ids=list(permission_group_ids or []),
            )
        )
