"""Use case: resolve + authorize the persona-invite context (workspace reads).

Owner-side read surface for the team persona-invite CREATE flow. ``workspace``
owns the models being read (``Workspace``/``WorkspaceMembership``/``WorkspaceGroup``
/``Team``), so the reads live here behind :class:`InviteContextReadPort`.

No Django imports — depends only on ports + DTOs.
"""

from __future__ import annotations

from components.workspace.application.ports.invite_context_read_port import (
    InviteContextReadPort,
    InviteContextResult,
)


class ReadInviteContextUseCase:
    def __init__(self, *, store: InviteContextReadPort) -> None:
        self._store = store

    def get_user_email(self, *, user_id: str) -> str | None:
        return self._store.get_user_email(user_id=user_id)

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
        return self._store.resolve(
            workspace_id=workspace_id,
            inviter_user_id=inviter_user_id,
            inviter_is_staff=inviter_is_staff,
            inviter_is_superuser=inviter_is_superuser,
            team_required=team_required,
            team_id=team_id,
            permission_group_ids=permission_group_ids,
        )
