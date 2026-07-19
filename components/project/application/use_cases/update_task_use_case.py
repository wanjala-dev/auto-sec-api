"""Use case for updating (patching) a task.

No Django imports — depends only on ports.
"""
from __future__ import annotations

from components.project.application.ports.update_task_port import (
    UpdateTaskCommand,
    UpdateTaskPort,
    UpdateTaskResult,
)


class UpdateTaskUseCase:
    def __init__(self, port: UpdateTaskPort) -> None:
        self._port = port

    def execute(self, *, command: UpdateTaskCommand) -> UpdateTaskResult:
        return self._port.update_task(command=command)
