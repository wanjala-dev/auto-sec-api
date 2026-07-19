"""Application-layer facade exposing team serializers to other bounded contexts.

Per Explicit Architecture rule 7, other contexts must not import directly
from our infrastructure layer. This facade provides the approved cross-context interface.
"""
from components.team.mappers.rest.team_serializers import (
    TeamSerializer,
    TeamSummarySerializer,
    TeamSummaryWithMembersSerializer,
    InvitationSerializer,
    TeamMembershipSummarySerializer,
)

__all__ = [
    "TeamSerializer",
    "TeamSummarySerializer",
    "TeamSummaryWithMembersSerializer",
    "InvitationSerializer",
    "TeamMembershipSummarySerializer",
]
