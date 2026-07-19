"""ORM-backed WorkspaceMembershipReaderPort."""

from __future__ import annotations

from typing import FrozenSet
from uuid import UUID

from components.social.application.ports.workspace_membership_reader_port import (
    WorkspaceMembershipReaderPort,
)
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership


class DjangoWorkspaceMembershipReader(WorkspaceMembershipReaderPort):
    def list_workspace_member_ids(self, workspace_id: UUID) -> FrozenSet[UUID]:
        membership_ids = WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).values_list("user_id", flat=True)
        team_member_ids = Team.objects.filter(
            workspace_id=workspace_id
        ).values_list("members__id", flat=True)
        owner_ids = Workspace.objects.filter(id=workspace_id).values_list(
            "workspace_owner_id", flat=True
        )
        combined = set()
        for source in (membership_ids, team_member_ids, owner_ids):
            combined.update(x for x in source if x is not None)
        return frozenset(combined)

    def is_workspace_owner(self, *, user_id: UUID, workspace_id: UUID) -> bool:
        return Workspace.objects.filter(
            id=workspace_id, workspace_owner_id=user_id
        ).exists()

    def list_user_team_ids(self, *, user_id: UUID, workspace_id: UUID) -> FrozenSet[int]:
        return frozenset(
            Team.objects.filter(
                workspace_id=workspace_id, members__id=user_id
            ).values_list("id", flat=True)
        )

    def is_team_member(self, *, user_id: UUID, team_id: int) -> bool:
        return Team.objects.filter(id=team_id, members__id=user_id).exists()
