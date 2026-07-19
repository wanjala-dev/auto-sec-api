"""Port: Column query operations.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColumnFilterRequest:
    """Parsed filter parameters for column queries."""

    column_id: Any | None = None
    project_id: Any | None = None
    team_id: Any | None = None
    workspace_id: Any | None = None
    user_assigned: bool = False
    user: Any | None = None


class ColumnQueryPort(abc.ABC):
    """Secondary port for column read queries."""

    @abc.abstractmethod
    def fetch_columns(self, *, request: ColumnFilterRequest) -> list[Any]:
        """Return filtered columns with tasks prefetched.

        Raises:
            WorkspaceNotFoundError: if workspace/team/project/column not found.
            TeamValidationError: if team doesn't belong to workspace.
            TeamMembershipRequiredError: if user isn't a team member.
            WorkspaceMembershipRequiredError: if user isn't a workspace member.
            WorkspaceValidationError: if required IDs are missing.
        """
        ...
