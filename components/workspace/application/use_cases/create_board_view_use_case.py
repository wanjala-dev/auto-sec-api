"""Use case: a user saves their current board lens as a personal view (task #74)."""

from __future__ import annotations

from typing import Any

from components.workspace.application.commands.board_view_commands import CreateBoardViewCommand
from components.workspace.application.ports.board_view_mutation_port import BoardViewMutationPort
from components.workspace.application.use_cases.validate_board_view_input import (
    validate_filter_shape,
    validate_group_by,
    validate_name,
)


class CreateBoardViewUseCase:
    def __init__(self, mutation_port: BoardViewMutationPort) -> None:
        self._port = mutation_port

    def execute(self, *, command: CreateBoardViewCommand, user: Any) -> Any:
        normalized = CreateBoardViewCommand(
            team_id=command.team_id,
            name=validate_name(command.name),
            filter=validate_filter_shape(command.filter if command.filter is not None else {}),
            group_by=validate_group_by(command.group_by if command.group_by is not None else "status"),
        )
        return self._port.create_view(command=normalized, user=user)
