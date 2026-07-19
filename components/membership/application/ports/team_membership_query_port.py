"""Team membership query port — read-only queries for team membership data.

Extracted from ``components.team.ports.team_membership_query_port``.
"""

from __future__ import annotations

import abc


class TeamMembershipQueryPort(abc.ABC):
    """Read-only team membership queries."""

    @abc.abstractmethod
    def list_user_teams(self, *, actor_id, user_id=None) -> list:
        """List teams the user belongs to."""

    @abc.abstractmethod
    def get_team_detail(
        self,
        *,
        team_id: int,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> object:
        """Get team detail with access control."""

    @abc.abstractmethod
    def list_workspace_teams(
        self,
        *,
        workspace_id,
        actor_id,
        team_name: str | None = None,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> tuple[list, bool]:
        """List teams in a workspace."""

    @abc.abstractmethod
    def list_workspace_team_members(
        self,
        *,
        workspace_id,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> tuple[list, dict]:
        """List all team members in a workspace."""

    @abc.abstractmethod
    def list_workspace_pending_invitations(
        self,
        *,
        workspace_id,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> list[dict]:
        """List pending invitations in a workspace."""
