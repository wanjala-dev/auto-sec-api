"""Use case: move a task to a different board.

Framework-free orchestration — delegates the actual reassignment (and its
membership + board validation) to the injected port.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.project.application.ports.move_task_to_board_port import (
    MoveTaskToBoardCommand,
    MoveTaskToBoardPort,
    MoveTaskToBoardResult,
)


@dataclass
class MoveTaskToBoardUseCase:
    port: MoveTaskToBoardPort

    def execute(self, *, command: MoveTaskToBoardCommand) -> MoveTaskToBoardResult:
        return self.port.move_task_to_board(command=command)
