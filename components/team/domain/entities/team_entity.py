"""Domain entity for a Team."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID

from components.team.domain.enums import TeamKind, TeamStatus


@dataclass(frozen=True)
class TeamEntity:
    """
    Domain entity for a team.

    A team groups workspace members around a common purpose.  Every workspace
    has at least one default team created during onboarding.
    """

    id: int
    workspace_id: UUID
    title: str
    created_by_id: int
    created_at: datetime.datetime
    plan_id: int
    kind: str
    status: str
    privacy: str
    plan_status: str = "active"
    plan_end_date: datetime.datetime | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id:
            raise ValueError("TeamEntity.workspace_id is required.")
        if not self.title:
            raise ValueError("TeamEntity.title is required.")

    @property
    def is_active(self) -> bool:
        return self.status == TeamStatus.ACTIVE

    @property
    def is_ai_agents(self) -> bool:
        return self.kind == TeamKind.AI_AGENTS
