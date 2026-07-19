"""Use case for batch-moving tasks across columns.

No Django imports — depends only on ports.
"""
from __future__ import annotations

from components.project.application.ports.batch_move_tasks_port import (
    BatchMoveTasksCommand,
    BatchMoveTasksPort,
    BatchMoveTasksResult,
)


class BatchMoveTasksUseCase:
    def __init__(self, port: BatchMoveTasksPort) -> None:
        self._port = port

    def execute(self, *, command: BatchMoveTasksCommand) -> BatchMoveTasksResult:
        return self._port.batch_move_tasks(command=command)
