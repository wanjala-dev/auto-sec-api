"""Port: Column query operations.

No Django imports — depends only on standard library.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

#: Default per-column task window for board reads. Board responses are ALWAYS
#: windowed (performance rule: pagination is not optional) — a lane with 9k
#: cards must never serialize 9k tasks into one response. Clients page the
#: remainder through ``fetch_column_tasks``.
DEFAULT_COLUMN_TASKS_LIMIT = 50
#: Hard ceiling a client may request per window.
MAX_COLUMN_TASKS_LIMIT = 200


def clamp_tasks_limit(raw: Any, *, default: int = DEFAULT_COLUMN_TASKS_LIMIT) -> int:
    """Coerce a client-supplied per-column window size into [1, MAX]."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, MAX_COLUMN_TASKS_LIMIT))


@dataclass(frozen=True)
class ColumnFilterRequest:
    """Parsed filter parameters for column queries."""

    column_id: Any | None = None
    project_id: Any | None = None
    team_id: Any | None = None
    workspace_id: Any | None = None
    user_assigned: bool = False
    user: Any | None = None
    #: Per-column task window size for board reads (always applied).
    tasks_limit: int = DEFAULT_COLUMN_TASKS_LIMIT


@dataclass(frozen=True)
class ColumnTasksPage:
    """One window of a single column's tasks, in board order."""

    tasks: list[Any]
    total: int
    offset: int
    limit: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.tasks) < self.total


class ColumnQueryPort(abc.ABC):
    """Secondary port for column read queries."""

    @abc.abstractmethod
    def fetch_columns(self, *, request: ColumnFilterRequest) -> list[Any]:
        """Return filtered columns with a windowed task list attached.

        Each returned column carries ``windowed_tasks`` (first
        ``request.tasks_limit`` live tasks in board order, eager-loaded for
        serialization) and ``tasks_total`` (live-task count) attributes.

        Raises:
            WorkspaceNotFoundError: if workspace/team/project/column not found.
            TeamValidationError: if team doesn't belong to workspace.
            TeamMembershipRequiredError: if user isn't a team member.
            WorkspaceMembershipRequiredError: if user isn't a workspace member.
            WorkspaceValidationError: if required IDs are missing.
        """
        ...

    @abc.abstractmethod
    def fetch_column_tasks(self, *, column_id: Any, user: Any, offset: int, limit: int) -> ColumnTasksPage:
        """Return one window of a column's live tasks in board order.

        The lane "load more" read. Same eager-loading + ordering contract as
        the windows attached by :meth:`fetch_columns`.

        Raises:
            WorkspaceNotFoundError: if the column doesn't exist.
            TeamMembershipRequiredError: if user isn't a team member (workspace
                admins/owners bypass, mirroring the board read).
            WorkspaceMembershipRequiredError: if user isn't a workspace member.
        """
        ...
