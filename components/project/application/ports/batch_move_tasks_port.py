"""Port: Batch task move operations.

No Django imports — depends only on standard library.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskMove:
    task_id: str
    column_id: str
    order: int | None = None


@dataclass(frozen=True)
class BatchMoveTasksCommand:
    moves: list[TaskMove]
    user_id: str


@dataclass
class BatchMoveTasksResult:
    success: bool = True
    updated_count: int = 0
    errors: list[str] = field(default_factory=list)


class BatchMoveTasksPort(abc.ABC):
    """Secondary port for batch task moves."""

    @abc.abstractmethod
    def batch_move_tasks(self, *, command: BatchMoveTasksCommand) -> BatchMoveTasksResult:
        """Move multiple tasks to new columns/positions in a single operation.

        Validates user membership, resolves all tasks and columns in bulk,
        performs bulk update, and emits workflow events for status transitions.

        Raises TeamMembershipRequiredError if user lacks access.
        Raises TaskNotFoundError if any task ID is invalid.
        """
        ...
