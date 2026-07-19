"""Resource DTOs (output schemas) for the team bounded context."""

from __future__ import annotations

from .team_resource import TeamResource, TeamSummaryResource, TeamCollectionResource
from .team_member_resource import TeamMemberResource, TeamMemberCollectionResource
from .invitation_resource import (
    InvitationResource,
    PendingInvitationResource,
    PendingInvitationCollectionResource,
    InvitationAcceptanceResource,
)

__all__ = [
    "TeamResource",
    "TeamSummaryResource",
    "TeamCollectionResource",
    "TeamMemberResource",
    "TeamMemberCollectionResource",
    "InvitationResource",
    "PendingInvitationResource",
    "PendingInvitationCollectionResource",
    "InvitationAcceptanceResource",
]
