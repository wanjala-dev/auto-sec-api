"""Port: Task update (patch) operations.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UpdateTaskCommand:
    task_id: str
    user_id: str
    data: dict[str, Any] = field(default_factory=dict)
    http_request: Any = None  # DRF request for serializer context


@dataclass
class UpdateTaskResult:
    success: bool = True
    task: dict[str, Any] = field(default_factory=dict)


class UpdateTaskPort(abc.ABC):
    """Secondary port for task update operations."""

    @abc.abstractmethod
    def update_task(self, *, command: UpdateTaskCommand) -> UpdateTaskResult:
        """Update a task with partial data.

        Validates workspace membership, team membership, keeps user
        profile in sync, performs partial update, emits workflow event
        on status transitions (e.g. task_completed).

        Raises NotFoundError if task does not exist.
        Raises WorkspaceMembershipRequiredError if user not in workspace.
        Raises TeamMembershipRequiredError if user not in task's team.
        Raises ValidationError if serializer data is invalid.
        """
        ...
