"""Team membership port — abstract interface for team enrollment operations.

Extracted from ``components.team.ports.team_membership_port``.
"""

from __future__ import annotations

import abc


class TeamMembershipPort(abc.ABC):
    """Team enrollment operations."""

    @abc.abstractmethod
    def get_or_create_default_team(self, workspace) -> object | None:
        """Get or create the default team for a workspace."""

    @abc.abstractmethod
    def enroll_user_in_team(
        self,
        user,
        workspace,
        team,
        *,
        mark_contributor: bool = True,
        update_active_context: bool = False,
    ) -> None:
        """Enroll a user in a team."""

    @abc.abstractmethod
    def ensure_contributor_membership(self, user, workspace) -> object | None:
        """Ensure user is a contributor in the default team."""
