"""Request DTOs (input schemas) for the team bounded context."""

from __future__ import annotations

from .create_team_request import CreateTeamRequest
from .update_team_request import UpdateTeamRequest
from .activate_team_request import ActivateTeamRequest
from .invite_team_members_request import InviteTeamMembersRequest
from .accept_invitation_request import AcceptInvitationRequest

__all__ = [
    "CreateTeamRequest",
    "UpdateTeamRequest",
    "ActivateTeamRequest",
    "InviteTeamMembersRequest",
    "AcceptInvitationRequest",
]
