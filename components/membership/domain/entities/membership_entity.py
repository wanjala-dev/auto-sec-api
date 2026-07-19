"""Domain entities for workspace and team memberships."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID

from components.membership.domain.enums import (
    WorkspaceMembershipRole,
    WorkspaceMembershipStatus,
)
from components.team.domain.enums import (
    TeamMembershipRole,
    TeamMembershipStatus,
)


@dataclass(frozen=True)
class WorkspaceMembershipEntity:
    """
    Domain entity for a workspace membership.

    Represents a user's role-aware participation in a workspace.
    """

    id: int
    workspace_id: UUID
    user_id: int
    role: str
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    invited_by_id: int | None = None

    @property
    def is_active(self) -> bool:
        return self.status == WorkspaceMembershipStatus.ACTIVE

    @property
    def is_owner(self) -> bool:
        return self.role == WorkspaceMembershipRole.OWNER

    @property
    def can_manage(self) -> bool:
        return self.role in {WorkspaceMembershipRole.OWNER, WorkspaceMembershipRole.ADMIN}


@dataclass(frozen=True)
class TeamMembershipEntity:
    """
    Domain entity for a team membership.

    Represents a user's role-aware participation in a team.
    """

    id: int
    team_id: int
    user_id: int
    role: str
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @property
    def is_active(self) -> bool:
        return self.status == TeamMembershipStatus.ACTIVE

    @property
    def is_lead(self) -> bool:
        return self.role == TeamMembershipRole.LEAD
