"""Use case for creating a task.

No Django imports — depends only on ports.
"""
from __future__ import annotations

from components.project.application.ports.create_task_port import (
    CreateTaskCommand,
    CreateTaskPort,
    CreateTaskResult,
)


class CreateTaskUseCase:
    def __init__(self, port: CreateTaskPort) -> None:
        self._port = port

    def execute(self, *, command: CreateTaskCommand) -> CreateTaskResult:
        return self._port.create_task(command=command)
