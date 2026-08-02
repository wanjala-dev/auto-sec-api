"""Port: Move a task to a DIFFERENT board (reassign team + project + column).

No Django imports — depends only on the standard library.

``batch_move_tasks`` only reassigns the ``column`` FK, so it cannot move a
task across boards: doing so would leave ``team`` / ``project`` pointing at the
source board while the card visually lives on the destination. This port
reassigns all three atomically. The destination board (team + project) is
DERIVED from the target column so the three can never disagree — the caller
supplies only the target column (and an optional order).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class MoveTaskToBoardCommand:
    task_id: str
    target_column_id: str
    user_id: str
    order: int | None = None


@dataclass(frozen=True)
class MoveTaskToBoardResult:
    task_id: str
    team_id: str
    project_id: str | None
    column_id: str
    order: int


class MoveTaskToBoardPort(abc.ABC):
    """Secondary port for moving a task onto another board."""

    @abc.abstractmethod
    def move_task_to_board(self, *, command: MoveTaskToBoardCommand) -> MoveTaskToBoardResult:
        """Reassign the task's team + project + column to the destination board.

        The destination board is the target column's own team + project. All
        three reassignments happen in a single transaction.

        Raises TaskNotFoundError if the task or target column is invalid.
        Raises WorkspaceMembershipRequiredError / TeamMembershipRequiredError if
        the caller lacks access to the DESTINATION board.
        Raises TaskValidationError if the move is not permitted (e.g. the
        destination column lives in a different workspace).
        """
        ...
