from __future__ import annotations

from typing import Protocol


class TeamMembershipPort(Protocol):
    def get_or_create_default_team(self, workspace):
        ...

    def enroll_user_in_team(
        self,
        user,
        workspace,
        team,
        *,
        mark_contributor: bool = True,
        update_active_context: bool = False,
    ) -> None:
        ...

    def ensure_contributor_membership(self, user, workspace):
        ...
