from __future__ import annotations

import uuid

from components.workspace.domain.errors import (
    TeamValidationError,
    WorkspaceAuthorizationError,
    WorkspaceValidationError,
)
from components.team.application.ports.team_membership_query_port import (
    TeamMembershipQueryPort,
)


class TeamMembershipQueryService:
    def __init__(self, *, team_membership_queries: TeamMembershipQueryPort) -> None:
        self.team_membership_queries = team_membership_queries

    def list_user_teams(
        self,
        *,
        actor_id,
        user_id=None,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> list:
        if not actor_id:
            raise WorkspaceAuthorizationError("Authentication required.")
        if user_id and not (is_staff or is_superuser) and str(actor_id) != str(user_id):
            raise WorkspaceAuthorizationError("You do not have permission to access this resource.")

        return self.team_membership_queries.list_user_teams(
            actor_id=actor_id,
            user_id=user_id,
        )

    def get_team_detail(
        self,
        *,
        team_id,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ):
        return self.team_membership_queries.get_team_detail(
            team_id=self._parse_team_id(team_id),
            actor_id=actor_id,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    def list_workspace_teams(
        self,
        *,
        workspace_id,
        actor_id,
        team_name: str | None = None,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> tuple[list, bool]:
        workspace_uuid = self._parse_workspace_id(workspace_id)
        return self.team_membership_queries.list_workspace_teams(
            workspace_id=workspace_uuid,
            actor_id=actor_id,
            team_name=team_name,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    def list_workspace_team_members(
        self,
        *,
        workspace_id,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> tuple[list, dict]:
        workspace_uuid = self._parse_workspace_id(workspace_id)
        return self.team_membership_queries.list_workspace_team_members(
            workspace_id=workspace_uuid,
            actor_id=actor_id,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    def list_workspace_pending_invitations(
        self,
        *,
        workspace_id,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> list[dict]:
        workspace_uuid = self._parse_workspace_id(workspace_id)
        return self.team_membership_queries.list_workspace_pending_invitations(
            workspace_id=workspace_uuid,
            actor_id=actor_id,
            is_staff=is_staff,
            is_superuser=is_superuser,
        )

    @staticmethod
    def _parse_workspace_id(workspace_id):
        if not workspace_id:
            raise WorkspaceValidationError("workspace_id is required.")
        try:
            return uuid.UUID(str(workspace_id), version=4)
        except (TypeError, ValueError) as exc:
            raise WorkspaceValidationError("workspace_id must be a valid UUID.") from exc

    @staticmethod
    def _parse_team_id(team_id):
        if not team_id:
            raise TeamValidationError("team_id is required.")
        try:
            return int(team_id)
        except (TypeError, ValueError) as exc:
            raise TeamValidationError("team_id must be a valid integer.") from exc
