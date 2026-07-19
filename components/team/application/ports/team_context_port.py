from __future__ import annotations

from typing import Any, Protocol


class TeamContextPort(Protocol):
    def get_accessible_team(
        self,
        *,
        team_id: int,
        actor_id,
        is_staff: bool = False,
        is_superuser: bool = False,
    ):
        ...

    def resolve_active_team(
        self,
        *,
        actor_id: Any,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> Any:
        """Resolve the user's active team from their profile and validate access."""
        ...

    def activate_team_for_user(self, *, actor_id, team) -> None:
        ...

    def activate_workspace_for_user(self, *, actor_id, workspace_id) -> None:
        """Persist the active workspace without a team (teamless members)."""
        ...
