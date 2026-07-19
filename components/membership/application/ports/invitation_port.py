"""Invitation port — abstract interface for invitation operations.

Centralises invitation issue / accept / query logic that was previously
scattered across the team bounded context.  Other contexts call this port
to manage team-membership invitations.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


# ── Commands ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class IssueInvitationCommand:
    """Command to issue a new invitation."""

    workspace_id: str
    team_id: int
    email: str
    invited_by_id: int


@dataclass(frozen=True)
class AcceptInvitationCommand:
    """Command to accept an invitation."""

    code: str
    user_id: int


@dataclass(frozen=True)
class InvitationResult:
    """Result of an invitation operation."""

    invitation_id: int
    status: str
    team_id: int
    workspace_id: str
    email: str


# ── Port ──────────────────────────────────────────────────────────────


class InvitationPort(abc.ABC):
    """Abstract interface for invitation operations."""

    @abc.abstractmethod
    def issue_invitation(
        self,
        *,
        command: IssueInvitationCommand,
    ) -> InvitationResult:
        """Issue a new invitation."""

    @abc.abstractmethod
    def accept_invitation(
        self,
        *,
        command: AcceptInvitationCommand,
    ) -> InvitationResult:
        """Accept a pending invitation."""

    @abc.abstractmethod
    def list_pending_invitations(
        self,
        *,
        workspace_id: str,
        team_id: int | None = None,
    ) -> list[InvitationResult]:
        """List pending invitations for a workspace/team."""


# ── Extended Team Invitation Port ─────────────────────────────────────


class TeamInvitationPort(abc.ABC):
    """Full team-invitation lifecycle port.

    Covers batch preparation, issuance, and acceptance for team
    membership invitations.  Extracted from components.team.
    """

    @abc.abstractmethod
    def prepare_invitation_batch(
        self,
        *,
        workspace_id,
        team_id,
        actor,
        normalized_emails: list[str],
        user_ids: list,
        is_staff: bool = False,
        is_superuser: bool = False,
    ) -> dict:
        """Validate and prepare a batch of invitations."""

    @abc.abstractmethod
    def accept_invitation(self, *, code: str, actor) -> object:
        """Accept a pending invitation by code."""

    @abc.abstractmethod
    def issue_invitation(
        self,
        *,
        workspace,
        team,
        invitee,
        email: str,
        actor_id,
    ) -> dict:
        """Issue a single invitation to an existing user."""
