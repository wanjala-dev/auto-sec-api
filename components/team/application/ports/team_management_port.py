from __future__ import annotations

from typing import Protocol


class TeamManagementPort(Protocol):
    def create_team(
        self,
        *,
        title: str,
        plan_id,
        workspace_id,
        actor,
    ):
        ...

    def update_active_team(
        self,
        *,
        actor,
        validated_data: dict,
        is_staff: bool = False,
        is_superuser: bool = False,
    ):
        ...
