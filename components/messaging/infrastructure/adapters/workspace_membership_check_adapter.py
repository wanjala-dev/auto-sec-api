"""Adapter for the WorkspaceMembershipCheckPort.

Delegates to ``shared_platform``'s platform-wide workspace-access
lookup rather than reaching into the workspaces bounded context's ORM
directly. Two users "share a workspace" when the intersection of their
accessible-workspace sets is non-empty (ownership, active membership,
or team membership all count — see ``OrmWorkspaceAccessAdapter``).
"""

from __future__ import annotations

from uuid import UUID


class WorkspaceMembershipCheckAdapter:
    """Concrete WorkspaceMembershipCheckPort backed by shared_platform."""

    def shares_workspace(self, user_a: UUID, user_b: UUID) -> bool:
        from components.shared_platform.application.providers.workspace_access_provider import (
            get_workspace_access_adapter,
        )

        access = get_workspace_access_adapter()
        a_ids = access.accessible_workspace_ids(user_id=user_a)
        if not a_ids:
            return False
        b_ids = access.accessible_workspace_ids(user_id=user_b)
        return bool(a_ids & b_ids)
