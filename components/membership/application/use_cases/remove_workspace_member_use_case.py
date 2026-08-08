"""Use case: remove a member from a workspace (revoke their membership).

The single choke point for membership revocation — the controller is a thin
caller, so no path can skip a rule:

1. The target must actually be a member (else ``NotFoundError`` → 404).
2. The workspace OWNER can never be removed (``ValidationError`` → 400).
   Ownership is structural; it is transferred, not revoked.
3. A member may always remove THEMSELVES (leave). Removing someone ELSE
   requires the ``manage_users`` capability, checked at the edge and asserted
   here via ``actor_can_manage_users`` so the rule is enforced in the use case
   too, not only in the controller.
4. Revocation is a soft status flip (the existing membership status machine),
   audited, and notified — all behind the port.

Idempotent: revoking an already-revoked membership is a success no-op.

No Django imports — depends only on ports and shared-kernel errors.
"""

from __future__ import annotations

import logging

from components.membership.application.ports.workspace_member_removal_port import (
    RemoveWorkspaceMemberCommand,
    RemoveWorkspaceMemberResult,
    WorkspaceMemberRemovalPort,
)
from components.shared_kernel.domain.errors import NotFoundError, AuthorizationError, ValidationError

logger = logging.getLogger(__name__)


class RemoveWorkspaceMemberUseCase:
    def __init__(self, port: WorkspaceMemberRemovalPort) -> None:
        self._port = port

    def execute(
        self,
        *,
        command: RemoveWorkspaceMemberCommand,
        actor_can_manage_users: bool,
    ) -> RemoveWorkspaceMemberResult:
        # 1. Membership must exist. Checked FIRST so a non-member never leaks
        #    "you lack permission" vs "no such member" through timing.
        role = self._port.find_membership_role(workspace_id=command.workspace_id, user_id=command.target_user_id)
        if role is None:
            raise NotFoundError("That user is not a member of this workspace.")

        # 2. Ownership is structural — never revocable here, not even by the
        #    owner themselves (an owner "leaving" would orphan the workspace).
        if self._port.is_workspace_owner(workspace_id=command.workspace_id, user_id=command.target_user_id):
            raise ValidationError("The workspace owner cannot be removed. Transfer ownership first.")

        # 3. Removing someone else requires manage_users; leaving is always allowed.
        if not command.is_self_removal and not actor_can_manage_users:
            raise AuthorizationError("You do not have permission to remove members.")

        result = self._port.revoke(command=command)
        logger.info(
            "workspace_member_removed workspace_id=%s target_user_id=%s actor_id=%s "
            "self_removal=%s removed=%s already_revoked=%s",
            command.workspace_id,
            command.target_user_id,
            command.performed_by,
            command.is_self_removal,
            result.removed,
            result.already_revoked,
        )
        return result
