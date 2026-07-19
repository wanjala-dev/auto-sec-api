"""ORM ↔ Entity mappers for Team aggregate.

These mappers live in the infrastructure boundary — they are the only
code that may import both ORM models and domain entities.
"""

from __future__ import annotations

from infrastructure.persistence.team.models import Invitation, Team, TeamMembership
from components.team.domain.entities.invitation_entity import InvitationEntity
from components.team.domain.entities.membership_entity import (
    TeamMembershipEntity,
)
from components.team.domain.entities.team_entity import TeamEntity


def to_team_entity(team: Team) -> TeamEntity:
    """Map a Django ORM Team to a TeamEntity."""
    return TeamEntity(
        id=team.id,
        workspace_id=team.workspace_id,
        title=team.title,
        created_by_id=team.created_by_id,
        created_at=team.created_at,
        plan_id=team.plan_id,
        kind=team.kind,
        status=team.status,
        privacy=team.privacy,
        plan_status=team.plan_status,
        plan_end_date=team.plan_end_date,
        stripe_customer_id=team.stripe_customer_id,
        stripe_subscription_id=team.stripe_subscription_id,
    )


def to_team_membership_entity(
    membership: TeamMembership,
) -> TeamMembershipEntity:
    """Map a Django ORM TeamMembership to a TeamMembershipEntity."""
    return TeamMembershipEntity(
        id=membership.id,
        team_id=membership.team_id,
        user_id=membership.user_id,
        role=membership.role,
        status=membership.status,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


def to_invitation_entity(invitation: Invitation) -> InvitationEntity:
    """Map a Django ORM Invitation to an InvitationEntity."""
    return InvitationEntity(
        id=invitation.id,
        workspace_id=invitation.workspace_id,
        team_id=invitation.team_id,
        email=invitation.email,
        code=invitation.code,
        status=invitation.status,
        date_sent=invitation.date_sent,
        accepted_at=invitation.accepted_at,
    )
