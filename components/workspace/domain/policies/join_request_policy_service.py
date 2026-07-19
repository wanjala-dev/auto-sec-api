"""Domain policy for workspace join requests.

Pure logic — no framework or ORM imports. Callers pass in primitive
values (IDs, privacy, role) and get back booleans/errors.
"""

from __future__ import annotations

from components.workspace.domain.errors import (
    JoinRequestPermissionError,
    JoinRequestValidationError,
)


class JoinRequestPolicyService:
    """Encapsulates who can request, review, or withdraw a join request."""

    @staticmethod
    def ensure_workspace_is_requestable(
        *,
        workspace_privacy: str,
        workspace_is_active: bool,
    ) -> None:
        """Only private + active workspaces accept join requests.

        Public workspaces use the follow flow; inactive/archived workspaces
        can't accept new members at all.
        """
        if not workspace_is_active:
            raise JoinRequestValidationError(
                "This workspace is no longer accepting new members."
            )
        if workspace_privacy != "private":
            raise JoinRequestValidationError(
                "Public workspaces are joined via the follow flow, not a "
                "join request."
            )

    @staticmethod
    def ensure_can_request(
        *,
        requester_is_owner: bool,
        requester_is_member: bool,
        has_pending_request: bool,
    ) -> None:
        if requester_is_owner:
            raise JoinRequestValidationError(
                "You already own this workspace."
            )
        if requester_is_member:
            raise JoinRequestValidationError(
                "You are already a member of this workspace."
            )
        if has_pending_request:
            raise JoinRequestValidationError(
                "You already have a pending join request for this workspace."
            )

    @staticmethod
    def ensure_can_review(
        *,
        reviewer_is_owner: bool,
        reviewer_is_admin: bool,
        reviewer_is_staff: bool,
    ) -> None:
        if not (reviewer_is_owner or reviewer_is_admin or reviewer_is_staff):
            raise JoinRequestPermissionError(
                "Only the workspace owner or an admin can review join requests."
            )

    @staticmethod
    def ensure_can_withdraw(
        *,
        requester_id: str,
        actor_id: str,
    ) -> None:
        if str(requester_id) != str(actor_id):
            raise JoinRequestPermissionError(
                "Only the requester can withdraw their own join request."
            )
