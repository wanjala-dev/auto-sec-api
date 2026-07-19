from __future__ import annotations

from typing import Protocol


class TeamMembershipQueryPort(Protocol):
    def list_user_teams(
        self,
        *,
        actor_id,
        user_id=None,
    ) -> list:
        ...

    def get_team_detail(
        self,
        *,
        team_id: int,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ):
        ...

    def list_workspace_teams(
        self,
        *,
        workspace_id,
        actor_id,
        team_name: str | None = None,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> tuple[list, bool]:
        ...

    def list_workspace_team_members(
        self,
        *,
        workspace_id,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> tuple[list, dict]:
        ...

    def list_workspace_pending_invitations(
        self,
        *,
        workspace_id,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> list[dict]:
        ...
