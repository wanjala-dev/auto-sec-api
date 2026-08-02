"""Adapter: resolve the invite context via ``workspace``'s read surface.

Implements the team-owned :class:`WorkspaceInviteContextPort` by delegating to
``workspace``'s ``ReadInviteContextUseCase`` (built by ``InviteContextProvider``)
— a permitted cross-context read into another context's application layer, never
its persistence (architecture-skill C3). It returns raw facts only; the use case
maps them to error + status code so the check ordering lives in one place and
matches ``main`` exactly.
"""

from __future__ import annotations

from components.team.application.ports.workspace_invite_context_port import (
    WorkspaceInviteContext,
    WorkspaceInviteContextPort,
)


class WorkspaceInviteContextAdapter(WorkspaceInviteContextPort):
    def get_inviter_email(self, *, inviter_user_id: str) -> str | None:
        from components.workspace.application.providers.invite_context_provider import (
            get_invite_context_provider,
        )

        use_case = get_invite_context_provider().build_use_case()
        return use_case.get_user_email(user_id=inviter_user_id)

    def resolve_invite_context(
        self,
        *,
        workspace_id: str,
        inviter_user_id: str | None,
        inviter_is_staff: bool,
        inviter_is_superuser: bool,
        persona: str,
        team_required: bool,
        team_id: str | None,
        permission_group_ids: list[str] | None,
    ) -> WorkspaceInviteContext:
        from components.workspace.application.providers.invite_context_provider import (
            get_invite_context_provider,
        )

        use_case = get_invite_context_provider().build_use_case()
        # Only attempt a team lookup when a team is required AND a team_id was
        # supplied — otherwise ``team_found`` stays True so the use case's own
        # "team_id required" 400 fires (never a spurious team-not-found 404).
        attempt_team_lookup = bool(team_required and team_id)
        result = use_case.resolve(
            workspace_id=workspace_id,
            inviter_user_id=inviter_user_id,
            inviter_is_staff=inviter_is_staff,
            inviter_is_superuser=inviter_is_superuser,
            team_required=attempt_team_lookup,
            team_id=team_id,
            permission_group_ids=permission_group_ids,
        )

        return WorkspaceInviteContext(
            workspace_found=result.workspace_found,
            authorized=result.authorized,
            team_found=result.team_found,
            validated_group_ids=result.validated_group_ids,
        )
