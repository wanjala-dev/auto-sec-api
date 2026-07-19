"""ORM ↔ Entity mappers for Workspace aggregate.

These mappers live in the infrastructure boundary — they are the only
code that may import both ORM models and domain entities.
"""

from __future__ import annotations

from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership
from components.membership.domain.entities.membership_entity import (
    WorkspaceMembershipEntity,
)
from components.workspace.domain.entities.workspace_entity import WorkspaceEntity


def to_workspace_entity(ws: Workspace) -> WorkspaceEntity:
    """Map a Django ORM Workspace to a WorkspaceEntity."""
    return WorkspaceEntity(
        id=ws.id,
        workspace_name=ws.workspace_name,
        workspace_owner_id=ws.workspace_owner_id,
        sector_id=str(ws.sector_id) if ws.sector_id else "",
        status=ws.status or "inactive",
        privacy=ws.privacy or "public",
        is_verified=ws.is_verified,
        is_active=ws.is_active,
        ai_teammate_enabled=ws.ai_teammate_enabled,
        notifications_enabled=ws.notifications_enabled,
        created_at=ws.created_at,
        updated_at=ws.updated_at,
        workspace_story=ws.workspace_story,
        photo_url=ws.photo_url or "",
        plan_id=ws.plan_id,
        plan_status=ws.plan_status or "active",
        stripe_customer_id=ws.stripe_customer_id,
        stripe_subscription_id=ws.stripe_subscription_id,
        subscription_payment_method_id=ws.subscription_payment_method_id,
    )


def to_workspace_membership_entity(
    membership: WorkspaceMembership,
) -> WorkspaceMembershipEntity:
    """Map a Django ORM WorkspaceMembership to a WorkspaceMembershipEntity."""
    return WorkspaceMembershipEntity(
        id=membership.id,
        workspace_id=membership.workspace_id,
        user_id=membership.user_id,
        role=membership.role,
        status=membership.status,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
        invited_by_id=membership.invited_by_id,
    )
