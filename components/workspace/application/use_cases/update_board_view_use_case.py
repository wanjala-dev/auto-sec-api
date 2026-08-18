"""Use case: rename / re-filter / reorder one of the user's saved views (task #74)."""

from __future__ import annotations

from typing import Any

from components.workspace.application.commands.board_view_commands import UpdateBoardViewCommand
from components.workspace.application.ports.board_view_mutation_port import BoardViewMutationPort
from components.workspace.application.use_cases.validate_board_view_input import (
    validate_filter_shape,
    validate_group_by,
    validate_name,
    validate_order,
)


class UpdateBoardViewUseCase:
    def __init__(self, mutation_port: BoardViewMutationPort) -> None:
        self._port = mutation_port

    def execute(self, *, command: UpdateBoardViewCommand, user: Any) -> Any:
        normalized = UpdateBoardViewCommand(
            view_id=command.view_id,
            name=validate_name(command.name) if command.name is not None else None,
            filter=validate_filter_shape(command.filter) if command.filter is not None else None,
            group_by=validate_group_by(command.group_by) if command.group_by is not None else None,
            order=validate_order(command.order) if command.order is not None else None,
        )
        return self._port.update_view(command=normalized, user=user)
