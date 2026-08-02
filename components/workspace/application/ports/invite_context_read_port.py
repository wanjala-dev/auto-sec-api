"""Port: workspace-side reads that back the persona-invite CREATE flow.

Validating the workspace, authorizing the inviter (owner/admin RBAC), resolving
a team for team-attached personas, and validating permission-group ownership all
read ``workspace``-owned models. This read port lets the team context obtain
those answers without importing ``workspace`` models (architecture-skill C3).

No Django imports.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class InviteContextResult:
    workspace_found: bool
    authorized: bool
    team_found: bool
    validated_group_ids: list[str]


class InviteContextReadPort(abc.ABC):
    @abc.abstractmethod
    def get_user_email(self, *, user_id: str) -> str | None: ...

    @abc.abstractmethod
    def resolve(
        self,
        *,
        workspace_id: str,
        inviter_user_id: str | None,
        inviter_is_staff: bool,
        inviter_is_superuser: bool,
        team_required: bool,
        team_id: str | None,
        permission_group_ids: list[str] | None,
    ) -> InviteContextResult: ...
