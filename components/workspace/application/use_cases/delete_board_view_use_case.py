"""Use case: delete one of the user's saved views (task #74)."""

from __future__ import annotations

from typing import Any

from components.workspace.application.ports.board_view_mutation_port import BoardViewMutationPort


class DeleteBoardViewUseCase:
    def __init__(self, mutation_port: BoardViewMutationPort) -> None:
        self._port = mutation_port

    def execute(self, *, view_id: Any, user: Any) -> None:
        self._port.delete_view(view_id=view_id, user=user)
