"""Domain entity for a Workspace (organisation)."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID

from components.workspace.domain.enums import WorkspacePrivacy, WorkspaceStatus


@dataclass(frozen=True)
class WorkspaceEntity:
    """
    Domain entity for a workspace.

    A workspace is the top-level organisational unit.  Users, teams, budgets,
    projects and all other bounded-context aggregates are scoped under a single
    workspace.
    """

    id: UUID
    workspace_name: str
    workspace_owner_id: int
    sector_id: str
    status: str
    privacy: str
    is_verified: bool
    is_active: bool
    ai_teammate_enabled: bool
    notifications_enabled: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime
    workspace_story: str | None = None
    photo_url: str = ""
    plan_id: int | None = None
    plan_status: str = "active"
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    subscription_payment_method_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.workspace_name:
            raise ValueError("WorkspaceEntity.workspace_name is required.")

    @property
    def is_public(self) -> bool:
        return self.privacy == WorkspacePrivacy.PUBLIC

    @property
    def is_operational(self) -> bool:
        return self.status == WorkspaceStatus.ACTIVE and self.is_active

    @property
    def has_story(self) -> bool:
        return bool(self.workspace_story and self.workspace_story.strip())

    @property
    def has_cover_photo(self) -> bool:
        return bool(self.photo_url and self.photo_url.strip())
